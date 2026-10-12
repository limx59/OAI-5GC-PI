/* SPDX-License-Identifier: LicenseRef-CSSL-1.0 */
/* Actual OAI MAC counters; no mobility control or synthetic load. */
#include "../../flexric/src/xApp/e42_xapp_api.h"
#include <assert.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static uint64_t reports[2];

static void emit(sm_ag_if_rd_t const* rd, unsigned index, uint32_t node)
{
  assert(rd && rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
  assert(rd->ind.type == MAC_STATS_V0);
  mac_ind_msg_t const* msg = &rd->ind.mac.msg;
  struct timespec received;
  clock_gettime(CLOCK_REALTIME, &received);
  int64_t received_us = (int64_t)received.tv_sec * 1000000
                      + received.tv_nsec / 1000;
  pthread_mutex_lock(&lock);
  ++reports[index];
  printf("MAC_REPORT {\"node\":%u,\"report_us\":%" PRId64
         ",\"received_us\":%" PRId64 ",\"ues\":%u,\"stats\":[",
         node, msg->tstamp, received_us, (unsigned)msg->len_ue_stats);
  for(size_t i = 0; i < msg->len_ue_stats; ++i) {
    mac_ue_stats_impl_t const* s = &msg->ue_stats[i];
    printf("%s{\"rnti\":%u,\"dl_bytes\":%" PRIu64
           ",\"ul_bytes\":%" PRIu64 ",\"dl_prb\":%u,\"ul_prb\":%u}",
           i ? "," : "", (unsigned)s->rnti,
           (uint64_t)s->dl_aggr_tbs, (uint64_t)s->ul_aggr_tbs,
           (unsigned)s->dl_aggr_prb, (unsigned)s->ul_aggr_prb);
  }
  printf("]}\n");
  fflush(stdout);
  pthread_mutex_unlock(&lock);
}
static void on_a(sm_ag_if_rd_t const* rd) { emit(rd, 0, 3584); }
static void on_b(sm_ag_if_rd_t const* rd) { emit(rd, 1, 2816); }

int main(int argc, char** argv)
{
  unsigned seconds = 60;
  char const* value = getenv("OAI_MAC_SECONDS");
  if(value) {
    char* end = NULL;
    unsigned long parsed = strtoul(value, &end, 10);
    if(!*value || *end || parsed < 5 || parsed > 600) {
      fprintf(stderr, "OAI_MAC_SECONDS must be 5..600\n");
      return EXIT_FAILURE;
    }
    seconds = (unsigned)parsed;
  }
  fr_args_t args = init_fr_args(argc, argv);
  init_xapp_api(&args);
  sleep(1);
  e2_node_arr_xapp_t nodes = e2_nodes_xapp_api();
  int indices[2] = {-1, -1};
  unsigned matches[2] = {0, 0};
  for(size_t i = 0; i < nodes.len; ++i) {
    if(nodes.n[i].id.plmn.mcc != 1 || nodes.n[i].id.plmn.mnc != 1
        || nodes.n[i].id.plmn.mnc_digit_len != 2)
      continue;
    for(unsigned j = 0; j < 2; ++j) {
      uint32_t node = j == 0 ? 3584 : 2816;
      if(nodes.n[i].id.nb_id.nb_id == node) {
        indices[j] = (int)i;
        ++matches[j];
      }
    }
  }
  bool valid = matches[0] == 1 && matches[1] == 1;
  for(unsigned j = 0; j < 2 && valid; ++j) {
    bool mac = false;
    for(size_t k = 0; k < nodes.n[indices[j]].len_rf; ++k)
      if(nodes.n[indices[j]].rf[k].id == 142)
        mac = true;
    valid = mac;
  }
  sm_ans_xapp_t handles[2] = {0};
  if(valid) {
    handles[0] = report_sm_xapp_api(
        &nodes.n[indices[0]].id, 142, (void*)"10_ms", on_a);
    if(handles[0].success)
      handles[1] = report_sm_xapp_api(
          &nodes.n[indices[1]].id, 142, (void*)"10_ms", on_b);
    valid = handles[0].success && handles[1].success;
    if(valid)
      sleep(seconds);
  }
  for(unsigned j = 0; j < 2; ++j)
    if(handles[j].success)
      rm_report_sm_xapp_api(handles[j].u.handle);
  free_e2_node_arr_xapp(&nodes);
  while(!try_stop_xapp_api())
    usleep(1000);
  pthread_mutex_lock(&lock);
  printf("MAC_SUMMARY {\"a_reports\":%" PRIu64
         ",\"b_reports\":%" PRIu64 ",\"subscriptions_ok\":%s}\n",
         reports[0], reports[1], valid ? "true" : "false");
  pthread_mutex_unlock(&lock);
  return valid ? EXIT_SUCCESS : EXIT_FAILURE;
}
