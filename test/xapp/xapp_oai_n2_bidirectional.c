/* SPDX-License-Identifier: LicenseRef-CSSL-1.0 */
/* Experimental bidirectional N2 context query and opt-in control. */
#include "../../flexric/src/xApp/e42_xapp_api.h"
#include "../../flexric/src/sm/rc_sm/ie/rc_data_ie.h"
#include "../../flexric/src/sm/rc_sm/ie/ir/ran_param_struct.h"
#include "../../flexric/src/sm/rc_sm/rc_sm_id.h"
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <semaphore.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static const uint32_t RC_REPORT_STYLE_ON_DEMAND = 5;
static sem_t indication;
static bool valid_report;
#include "../../flexric/src/util/conversions.h"
static const uint32_t RC_CTRL_STYLE_CONN_MODE_MOBILITY = 3;
static bool target_present;
static uint32_t source_node = 3584;
static uint64_t source_cell = 12345678;
static uint64_t destination_cell = 720898;
typedef struct {
  bool connected;
  ue_id_e2sm_t ue_id;
  nr_cgi_t serving_cell;
  size_t sz_neighbour_cells;
  nr_cgi_t *neighbour_cells;
} ue_cell_t;

static ue_cell_t ue_cell = {0};

static
byte_array_t* encode_nr_cgi_plmn_cell(const nr_cgi_t* nr_cgi)
{
  byte_array_t *dst = calloc(1, sizeof(*dst));
  assert(dst != NULL && "Memory exhausted");
  dst->len = 8;
  dst->buf = calloc(dst->len, sizeof(uint8_t));
  assert(dst->buf != NULL && "Memory exhausted");

  const int mcc = nr_cgi->plmn_id.mcc;
  const int mnc = nr_cgi->plmn_id.mnc;
  const int mnc_digit_len = nr_cgi->plmn_id.mnc_digit_len;
  dst->buf[0] = (MCC_MNC_DECIMAL(mcc) << 4) | MCC_HUNDREDS(mcc);
  dst->buf[1] = (MNC_HUNDREDS(mnc, mnc_digit_len) << 4) | MCC_MNC_DIGIT(mcc);
  dst->buf[2] = (MCC_MNC_DIGIT(mnc) << 4) | MCC_MNC_DECIMAL(mnc);

  const uint64_t cell_id = nr_cgi->nr_cell_id;
  dst->buf[3] = (cell_id >> 28) & 0xFF;
  dst->buf[4] = (cell_id >> 20) & 0xFF;
  dst->buf[5] = (cell_id >> 12) & 0xFF;
  dst->buf[6] = (cell_id >> 4) & 0xFF;
  dst->buf[7] = (cell_id & 0xF) << 4;

  return dst;
}

// Wrap one RAN parameter in a single-element STRUCTURE value.
static
ran_param_val_type_t wrap_in_struct(seq_ran_param_t inner)
{
  ran_param_val_type_t dst = {.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE};

  dst.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(dst.strct != NULL && "Memory exhausted");

  dst.strct->sz_ran_param_struct = 1;
  dst.strct->ran_param_struct = calloc(1, sizeof(seq_ran_param_t));
  assert(dst.strct->ran_param_struct != NULL && "Memory exhausted");
  dst.strct->ran_param_struct[0] = inner;

  return dst;
}

/* Target Primary Cell ID > CHOICE Target Cell > NR Cell ID > NR CGI, the
 * nested shape 8.4.4.1 prescribes for Handover Control. Takes ownership of
 * nr_cgi's buffer. */
static
seq_ran_param_t fill_target_primary_cell_id(byte_array_t nr_cgi)
{
  seq_ran_param_t nr_cgi_p = {.ran_param_id = NR_CGI_8_4_4_1};
  nr_cgi_p.ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  nr_cgi_p.ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(nr_cgi_p.ran_param_val.flag_false != NULL && "Memory exhausted");
  nr_cgi_p.ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  nr_cgi_p.ran_param_val.flag_false->octet_str_ran = nr_cgi;

  seq_ran_param_t nr_cell_id_p = {.ran_param_id = NR_CELL_8_4_4_1};
  nr_cell_id_p.ran_param_val = wrap_in_struct(nr_cgi_p);

  seq_ran_param_t choice_target_cell = {.ran_param_id = CHOICE_TARGET_CELL_8_4_4_1};
  choice_target_cell.ran_param_val = wrap_in_struct(nr_cell_id_p);

  seq_ran_param_t dst = {.ran_param_id = TARGET_PRIMARY_CELL_ID_8_4_4_1};
  dst.ran_param_val = wrap_in_struct(choice_target_cell);

  return dst;
}

/* Takes ownership of nr_cgi's buffer. */
static
rc_ctrl_req_data_t gen_handover_ctrl(byte_array_t nr_cgi)
{
  rc_ctrl_req_data_t dst = {0};

  // CONTROL HEADER, 9.2.2.11
  dst.hdr.format = FORMAT_1_E2SM_RC_CTRL_HDR;
  dst.hdr.frmt_1.ric_style_type = RC_CTRL_STYLE_CONN_MODE_MOBILITY;
  dst.hdr.frmt_1.ctrl_act_id = HANDOVER_CONTROL_7_6_4_1;
  dst.hdr.frmt_1.ue_id = cp_ue_id_e2sm(&ue_cell.ue_id);

  // CONTROL MESSAGE, 9.2.2.12
  dst.msg.format = FORMAT_1_E2SM_RC_CTRL_MSG;
  dst.msg.frmt_1.sz_ran_param = 1;
  dst.msg.frmt_1.ran_param = calloc(1, sizeof(seq_ran_param_t));
  assert(dst.msg.frmt_1.ran_param != NULL && "Memory exhausted");
  dst.msg.frmt_1.ran_param[0] = fill_target_primary_cell_id(nr_cgi);

  return dst;
}

static
bool supports_handover_ctrl(const ran_func_def_ctrl_t* ctrl)
{
  if (ctrl == NULL)
    return false;

  for (size_t i = 0; i < ctrl->sz_seq_ctrl_style; i++) {
    const seq_ctrl_style_t* style = &ctrl->seq_ctrl_style[i];
    if (style->style_type != RC_CTRL_STYLE_CONN_MODE_MOBILITY)
      continue;

    for (size_t j = 0; j < style->sz_seq_ctrl_act; j++)
      if (style->seq_ctrl_act[j].id == HANDOVER_CONTROL_7_6_4_1)
        return true;
  }

  return false;
}

static
bool supports_on_demand_report(const ran_func_def_report_t* report)
{
  if (report == NULL)
    return false;

  for (size_t i = 0; i < report->sz_seq_report_sty; i++) {
    const seq_report_sty_t* style = &report->seq_report_sty[i];
    if (style->report_type != RC_REPORT_STYLE_ON_DEMAND)
      continue;

    bool has_ue_ctx_info = false;
    bool has_neighbour_tbl = false;

    for (size_t j = 0; j < style->sz_seq_ran_param; j++) {
      if (style->ran_param[j].id == E2SM_RC_RS5_UE_CONTEXT_INFORMATION)
        has_ue_ctx_info = true;
      else if (style->ran_param[j].id == E2SM_RC_RS5_NEIGHBOUR_RELATION_TABLE)
        has_neighbour_tbl = true;
    }

    if (has_ue_ctx_info && has_neighbour_tbl)
      return true;
  }

  return false;
}

static
param_report_def_t fill_param_report(uint32_t const ran_param_id, ran_param_def_t const* ran_param_def)
{
  param_report_def_t param_report = {0};

  param_report.ran_param_id = ran_param_id;
  if (ran_param_def != NULL) {
    param_report.ran_param_def = calloc(1, sizeof(ran_param_def_t));
    assert(param_report.ran_param_def != NULL && "Memory exhausted");
    *param_report.ran_param_def = cp_ran_param_def(ran_param_def);
  }

  return param_report;
}

/* REPORT Service Style 5 ("On Demand Report", E2SM-RC v01.03 7.4.6): Event
 * Trigger Format 5 (on demand, no per-UE/cell scoping). */
static
rc_sub_data_t gen_rc_sub_style_5(void)
{
  rc_sub_data_t rc_sub = {0};

  // Generate Event Trigger
  rc_sub.et.format = FORMAT_5_E2SM_RC_EV_TRIGGER_FORMAT;
  rc_sub.et.frmt_5.on_demand = TRUE_ON_DEMAND_FRMT_5;
  rc_sub.et.frmt_5.assoc_ue_info = NULL;
  rc_sub.et.frmt_5.assoc_cell_info = NULL;

  // Generate Action Definition
  rc_sub.sz_ad = 1;
  rc_sub.ad = calloc(rc_sub.sz_ad, sizeof(e2sm_rc_action_def_t));
  assert(rc_sub.ad != NULL && "Memory exhausted");
  rc_sub.ad[0].ric_style_type = RC_REPORT_STYLE_ON_DEMAND;
  rc_sub.ad[0].format = FORMAT_1_E2SM_RC_ACT_DEF;
  rc_sub.ad[0].frmt_1.sz_param_report_def = 2;
  rc_sub.ad[0].frmt_1.param_report_def = calloc(rc_sub.ad[0].frmt_1.sz_param_report_def, sizeof(param_report_def_t));
  assert(rc_sub.ad[0].frmt_1.param_report_def != NULL && "Memory exhausted");
  rc_sub.ad[0].frmt_1.param_report_def[0] = fill_param_report(E2SM_RC_RS5_UE_CONTEXT_INFORMATION, NULL);
  rc_sub.ad[0].frmt_1.param_report_def[1] = fill_param_report(E2SM_RC_RS5_NEIGHBOUR_RELATION_TABLE, NULL);

  return rc_sub;
}


static void callback(sm_ag_if_rd_t const* rd)
{
  if(rd == NULL || rd->type != INDICATION_MSG_AGENT_IF_ANS_V0
      || rd->ind.rc.ind.msg.format != FORMAT_4_E2SM_RC_IND_MSG) {
    fprintf(stderr, "Unexpected RC indication\n");
    sem_post(&indication);
    return;
  }
  const e2sm_rc_ind_msg_frmt_4_t* msg = &rd->ind.rc.ind.msg.frmt_4;
  printf("RC context: UEs=%zu cells=%zu\n",
         msg->sz_seq_ue_info, msg->sz_seq_cell_info_2);

  if(msg->sz_seq_ue_info == 1
      && msg->seq_ue_info[0].ue_id.type == GNB_UE_ID_E2SM) {
    ue_cell.ue_id = cp_ue_id_e2sm(&msg->seq_ue_info[0].ue_id);
    ue_cell.serving_cell =
        cp_nr_cgi(&msg->seq_ue_info[0].cell_global_id.nr_cgi);
    ue_cell.connected = true;
  }
  for(size_t i = 0; i < msg->sz_seq_ue_info; ++i) {
    const seq_ue_info_t* ue = &msg->seq_ue_info[i];
    const nr_cgi_t* cell = &ue->cell_global_id.nr_cgi;
    printf("UE[%zu]: serving MCC=%u MNC=%u digits=%u cell=%" PRIu64 "\n",
           i, cell->plmn_id.mcc, cell->plmn_id.mnc,
           cell->plmn_id.mnc_digit_len, (uint64_t)cell->nr_cell_id);
  }
  for(size_t i = 0; i < msg->sz_seq_cell_info_2; ++i) {
    const seq_cell_info_2_t* cell = &msg->seq_cell_info_2[i];
    if(cell->neighbour_rela_tbl == NULL)
      continue;
    for(size_t j = 0;
        j < cell->neighbour_rela_tbl->sz_neighbour_cell_list; ++j) {
      if(cell->neighbour_rela_tbl->neighbour_cell_list[j].type
          != NR_NEIGHBOUR_CELL_E2SM_RC)
        continue;
      const nr_cgi_t* neighbour =
          &cell->neighbour_rela_tbl->neighbour_cell_list[j].choice_nr.nr_cgi;

      if(ue_cell.connected
          && eq_nr_cgi(&cell->cell_global_id.nr_cgi, &ue_cell.serving_cell)
          && neighbour->plmn_id.mcc == 1
          && neighbour->plmn_id.mnc == 1
          && neighbour->plmn_id.mnc_digit_len == 2
          && neighbour->nr_cell_id == destination_cell)
        target_present = true;
      printf("Neighbour: MCC=%u MNC=%u digits=%u cell=%" PRIu64 "\n",
             neighbour->plmn_id.mcc, neighbour->plmn_id.mnc,
             neighbour->plmn_id.mnc_digit_len,
             (uint64_t)neighbour->nr_cell_id);
    }
  }
  valid_report = msg->sz_seq_ue_info == 1;
  sem_post(&indication);
}

int main(int argc, char* argv[])
{
  char const* direction = getenv("OAI_N2_DIRECTION");
  if(direction != NULL && strcmp(direction, "B_TO_A") == 0) {
    source_node = 2816;
    source_cell = 720898;
    destination_cell = 12345678;
  } else if(direction != NULL && strcmp(direction, "A_TO_B") != 0) {
    fprintf(stderr, "Invalid OAI_N2_DIRECTION; use A_TO_B or B_TO_A\n");
    return EXIT_FAILURE;
  }
  printf("Direction: node=%u source=%" PRIu64 " target=%" PRIu64 "\n",
         source_node, source_cell, destination_cell);
  fr_args_t args = init_fr_args(argc, argv);
  if(sem_init(&indication, 0, 0) != 0)
    return EXIT_FAILURE;
  init_xapp_api(&args);
  sleep(1);
  e2_node_arr_xapp_t nodes = e2_nodes_xapp_api();
  int result = EXIT_FAILURE;
  e2_node_connected_xapp_t* source = NULL;
  for(size_t i = 0; i < nodes.len; ++i) {
    if(nodes.n[i].id.nb_id.nb_id != source_node
        || nodes.n[i].id.plmn.mcc != 1
        || nodes.n[i].id.plmn.mnc != 1)
      continue;
    if(source != NULL) {
      fprintf(stderr, "Ambiguous source node\n");
      goto stop;
    }
    source = &nodes.n[i];
  }
  if(source == NULL) {
    fprintf(stderr, "Source gNB %u / PLMN 00101 not found\n", source_node);
    goto stop;
  }
  bool supported = false;
  for(size_t i = 0; i < source->len_rf; ++i)
    if(source->rf[i].id == SM_RC_ID)
      supported = supports_on_demand_report(source->rf[i].defn.rc.report);
  if(!supported) {
    fprintf(stderr, "Source lacks RC Style 5 context/neighbour capability\n");
    goto stop;
  }
  rc_sub_data_t sub = gen_rc_sub_style_5();
  sm_ans_xapp_t answer =
      report_sm_xapp_api(&source->id, SM_RC_ID, &sub, callback);
  free_rc_sub_data(&sub);
  if(!answer.success) {
    fprintf(stderr, "Context subscription submission failed\n");
    goto stop;
  }
  struct timespec deadline;
  clock_gettime(CLOCK_REALTIME, &deadline);
  deadline.tv_sec += 15;
  int rc;
  do {
    rc = sem_timedwait(&indication, &deadline);
  } while(rc != 0 && errno == EINTR);
  rm_report_sm_xapp_api(answer.u.handle);
  if(rc == 0 && valid_report) {

    char const* enabled = getenv("OAI_N2_CONTROL_TEST");
    if(enabled != NULL && strcmp(enabled, "1") == 0) {
      bool control_supported = false;
      for(size_t i = 0; i < source->len_rf; ++i)
        if(source->rf[i].id == SM_RC_ID)
          control_supported =
              supports_handover_ctrl(source->rf[i].defn.rc.ctrl);
      if(!control_supported || !ue_cell.connected || !target_present
          || ue_cell.serving_cell.plmn_id.mcc != 1
          || ue_cell.serving_cell.plmn_id.mnc != 1
          || ue_cell.serving_cell.plmn_id.mnc_digit_len != 2
          || ue_cell.serving_cell.nr_cell_id != source_cell) {
        fprintf(stderr, "Control preconditions failed; no request sent\n");
        goto stop;
      }
      nr_cgi_t target_cell = ue_cell.serving_cell;
      target_cell.nr_cell_id = destination_cell;
      byte_array_t* encoded = encode_nr_cgi_plmn_cell(&target_cell);
      rc_ctrl_req_data_t control = gen_handover_ctrl(*encoded);
      free(encoded);
      printf("Submitting N2 control: source=%" PRIu64 " target=%" PRIu64 "\n",
             source_cell, destination_cell);
      sm_ans_xapp_t sent =
          control_sm_xapp_api(&source->id, SM_RC_ID, &control);
      free_rc_ctrl_req_data(&control);
      if(!sent.success) {
        fprintf(stderr, "Control submission failed\n");
        goto stop;
      }
      printf("Control submitted; handover completion requires external verification\n");
    } else {
      printf("PASS: one UE context received; no control request sent\n");
    }

    result = EXIT_SUCCESS;
  } else {
    fprintf(stderr, "Context query failed or timed out\n");
  }
stop:
  free_e2_node_arr_xapp(&nodes);
  /* Container invocation must also enforce an overall timeout. */
  while(!try_stop_xapp_api())
    usleep(1000);
  if(ue_cell.connected)
    free_ue_id_e2sm(&ue_cell.ue_id);
  sem_destroy(&indication);
  return result;
}
