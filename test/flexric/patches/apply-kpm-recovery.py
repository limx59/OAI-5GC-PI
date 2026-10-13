#!/usr/bin/env python3
"""Apply KPM recovery changes only to the dedicated image's source copy."""

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply-kpm-recovery.py /src/flexric")
target = Path(sys.argv[1]).resolve()
if target != Path("/src/flexric") or not target.is_dir():
    raise SystemExit("Only the container source copy /src/flexric is allowed.")

helper = (
    Path(__file__).resolve().parent.parent
    / "native/subscription_request_copy.h"
)
header = helper.read_text(encoding="utf-8")
old_include = '#include "../../../flexric/src/lib/e2ap/'
if header.count(old_include) != 3:
    raise SystemExit("Unexpected helper include paths.")
header = header.replace(old_include, '#include "../lib/e2ap/')
destination = target / "src/xApp/subscription_request_copy.h"
if destination.exists():
    raise SystemExit("Source copy already contains the helper.")

changes = {
    "src/xApp/act_proc.h": (
        (
            "#include <stdint.h>",
            '#include <stdint.h>\n#include "subscription_request_copy.h"',
        ),
        (
            "  global_e2_node_id_t e2_node;",
            "  global_e2_node_id_t e2_node;\n"
            "  ric_subscription_request_t* saved_subscription;",
        ),
        (
            "void init_act_proc(act_proc_t* proc);",
            "void save_subscription_act_proc(act_proc_t* proc, uint16_t request_id,\n"
            "                                const ric_subscription_request_t* request);\n\n"
            "void init_act_proc(act_proc_t* proc);",
        ),
    ),
    "src/xApp/act_proc.c": (
        (
            "  free_global_e2_node_id(&v->e2_node);",
            """  free_global_e2_node_id(&v->e2_node);
  if (v->saved_subscription != NULL) {
    free_saved_subscription_request_xapp(v->saved_subscription);
    free(v->saved_subscription);
    v->saved_subscription = NULL;
  }""",
        ),
        (
            "  assoc_reg_free(&p->reg);",
            """  assoc_reg_erase(&p->reg,
                  assoc_reg_front(&p->reg),
                  assoc_reg_end(&p->reg),
                  free_act_proc_val);
  assoc_reg_free(&p->reg);""",
        ),
    ),
    "src/xApp/e42_xapp.c": (
        (
            "  ric_subscription_request_t sr = generate_subscription_request(ric_id, sm, data);",
            "  ric_subscription_request_t sr = generate_subscription_request(ric_id, sm, data);\n"
            "  save_subscription_act_proc(&xapp->act_proc, ric_id.ric_req_id, &sr);",
        ),
    ),
}

# Graceful SCTP disconnect and Setup retry
changes["src/xApp/endpoint_xapp.h"] = (
    (
        "byte_array_t e2ap_recv_msg_xapp(e2ap_ep_xapp_t* ep);",
        "sctp_msg_t e2ap_recv_msg_xapp(e2ap_ep_xapp_t* ep);",
    ),
)
changes["src/xApp/endpoint_xapp.c"] = (
    (
        "  evnts.sctp_data_io_event = 1 ;",
        "  evnts.sctp_data_io_event = 1 ;\n"
        "  evnts.sctp_shutdown_event = 1;",
    ),
    (
        """byte_array_t e2ap_recv_msg_xapp(e2ap_ep_xapp_t* ep)
{
  assert(ep != NULL);

  sctp_msg_t rcv = e2ap_recv_sctp_msg(&ep->base); //, &ba);

//sctp_msg_t e2ap_recv_sctp_msg(e2ap_ep_t* ep);
  return rcv.ba;
//  e2ap_msg_t msg = e2ap_msg_dec(&enc->type, ba);
  //printf("Message received in the iapp\\n");
//  return msg;
}""",
        """sctp_msg_t e2ap_recv_msg_xapp(e2ap_ep_xapp_t* ep)
{
  assert(ep != NULL);
  return e2ap_recv_sctp_msg(&ep->base);
}""",
    ),
)
changes["src/xApp/e42_xapp.c"] += (
    (
        """      byte_array_t ba = e2ap_recv_msg_xapp(&xapp->ep);
      defer( {free_byte_array(ba);} );""",
        """      sctp_msg_t received = e2ap_recv_msg_xapp(&xapp->ep);
      defer({ free_sctp_msg(&received); });
      if (received.type == SCTP_MSG_NOTIFICATION) {
        if (received.notif->sn_header.sn_type == SCTP_SHUTDOWN_EVENT &&
            atomic_exchange(&xapp->connected, false)) {
          {
            lock_guard(&xapp->conn_mtx);
            free_reg_e2_node(&xapp->e2_nodes);
            init_reg_e2_node(&xapp->e2_nodes);
          }
          printf("[KPM recovery]: RIC disconnected; restarting Setup\\n");
          send_setup_request(xapp);
        }
        continue;
      }
      assert(received.type == SCTP_MSG_PAYLOAD);
      byte_array_t ba = received.ba;""",
    ),
)

# Replay saved subscriptions after node registration
changes["src/xApp/act_proc.h"] += (
    (
        "  ric_subscription_request_t* saved_subscription;",
        "  ric_subscription_request_t* saved_subscription;\n"
        "  bool needs_replay;\n"
        "  bool replay_ack_pending;",
    ),
)

replay_function = """
static void replay_saved_subscriptions(e42_xapp_t* xapp)
{
  if (!atomic_load(&xapp->connected))
    return;

  lock_guard(&xapp->act_proc.mtx);
  assoc_reg_t* reg = &xapp->act_proc.reg;
  void* end = assoc_reg_end(reg);
  for (void* it = assoc_reg_front(reg); it != end;
       it = assoc_reg_next(reg, it)) {
    act_proc_val_t* value = assoc_reg_value(reg, it);
    if (!value->needs_replay || value->saved_subscription == NULL)
      continue;
    if (!find_reg_e2_node(&xapp->e2_nodes, &value->e2_node))
      continue;

    uint32_t request_id = *(uint32_t*)assoc_reg_key(reg, it);
    assert(request_id < (1u << 16));
    value->id.ric_req_id = request_id;
    value->needs_replay = false;
    value->replay_ack_pending = true;

    e42_ric_subscription_request_t request = {
      .xapp_id = xapp->id,
      .id = cp_global_e2_node_id(&value->e2_node),
      .sr = copy_subscription_request_xapp(value->saved_subscription),
    };
    request.sr.ric_id = value->id;
    defer({ e2ap_free_e42_ric_subscription_request(&request); });
    e2ap_msg_t message = {
      .type = E42_RIC_SUBSCRIPTION_REQUEST,
      .u_msgs.e42_ric_sub_req = request,
    };
    printf("[KPM recovery]: replay request=%u\\n", request_id);
    xapp->handle_msg[E42_RIC_SUBSCRIPTION_REQUEST](xapp, &message);
  }
}
"""

changes["src/xApp/e42_xapp.c"] += (
    (
        "static\nvoid e2_event_loop_xapp(e42_xapp_t* xapp)",
        replay_function + "\nstatic\nvoid e2_event_loop_xapp(e42_xapp_t* xapp)",
    ),
    (
        '          printf("[KPM recovery]: RIC disconnected; restarting Setup\\n");',
        """          {
            lock_guard(&xapp->act_proc.mtx);
            assoc_reg_t* reg = &xapp->act_proc.reg;
            void* end = assoc_reg_end(reg);
            for (void* it = assoc_reg_front(reg); it != end;
                 it = assoc_reg_next(reg, it)) {
              act_proc_val_t* value = assoc_reg_value(reg, it);
              if (value->saved_subscription != NULL) {
                value->needs_replay = true;
                value->replay_ack_pending = false;
              }
            }
          }
          printf("[KPM recovery]: RIC disconnected; restarting Setup\\n");""",
    ),
    (
        "      e2ap_msg_t ans = e2ap_msg_handle_xapp(xapp, &msg);",
        "      e2ap_msg_t ans = e2ap_msg_handle_xapp(xapp, &msg);\n"
        "      replay_saved_subscriptions(xapp);",
    ),
)

changes["src/xApp/msg_handler_xapp.c"] = (
    (
        """  // Remove pending event\x20\x20
  rm_pending_event_xapp(xapp, &ev);

  // Unblock UI thread\x20\x20
  signal_sync_ui(&xapp->sync);""",
        """  // Remove pending event
  rm_pending_event_xapp(xapp, &ev);

  bool replay_ack = false;
  {
    lock_guard(&xapp->act_proc.mtx);
    assoc_reg_t* reg = &xapp->act_proc.reg;
    void* it = find_reg(reg, assoc_reg_front(reg),
                        assoc_reg_end(reg), resp->ric_id.ric_req_id);
    assert(it != assoc_reg_end(reg));
    act_proc_val_t* value = assoc_reg_value(reg, it);
    replay_ack = value->replay_ack_pending;
    value->replay_ack_pending = false;
  }
  if (replay_ack) {
    printf("[KPM recovery]: replay ACK request=%u\\n",
           resp->ric_id.ric_req_id);
  } else {
    signal_sync_ui(&xapp->sync);
  }""",
    ),
    (
        """  e2ap_send_bytes_xapp(&xapp->ep, ba);

  printf("[xApp]: E42 SETUP-REQUEST tx\\n");""",
        """  printf("[xApp]: E42 SETUP-REQUEST tx\\n");""",
    ),
    (
        "  add_pending_event_xapp(xapp, &x_ev);",
        "  add_pending_event_xapp(xapp, &x_ev);\n"
        "  e2ap_send_bytes_xapp(&xapp->ep, ba);",
    ),
)

# Agent association notifications and duplicate Setup guard
changes["src/agent/endpoint_agent.c"] = (
    (
        "  struct sctp_event_subscribe evnts = { .sctp_data_io_event = 1,",
        "  struct sctp_event_subscribe evnts = { .sctp_association_event = 1,\n"
        "                                        .sctp_data_io_event = 1,",
    ),
)

changes["src/agent/not_handler_agent.c"] = (
    (
        '#include "not_handler_agent.h"',
        '#include "not_handler_agent.h"\n'
        '#include "../util/alg_ds/alg/alg.h"',
    ),
    (
        "void notification_handle_ag(e2_agent_t* ag, sctp_msg_t const* msg)",
        """static bool same_pending_event(const void* left, const void* right)
{
  return *(const pending_event_t*)left == *(const pending_event_t*)right;
}

void notification_handle_ag(e2_agent_t* ag, sctp_msg_t const* msg)""",
    ),
    (
        "  assert(msg != NULL && msg->type == SCTP_MSG_NOTIFICATION);",
        """  assert(msg != NULL && msg->type == SCTP_MSG_NOTIFICATION);

  unsigned int type = msg->notif->sn_header.sn_type;
  if (type == SCTP_ASSOC_CHANGE) {
    unsigned int state = msg->notif->sn_assoc_change.sac_state;
    if (state != SCTP_COMM_LOST && state != SCTP_RESTART &&
        state != SCTP_CANT_STR_ASSOC)
      return;
    printf("[KPM recovery]: Agent association change state=%u\\n", state);
  } else if (type != SCTP_SHUTDOWN_EVENT) {
    return;
  }""",
    ),
    (
        """  #ifdef PROXY_AGENT
  lock_guard(&ag->pend_mtx);
  #endif
""",
        "",
    ),
    (
        "  long const wait_ms = 3000;",
        """  #ifdef PROXY_AGENT
  lock_guard(&ag->pend_mtx);
  #endif
  assoc_rb_tree_t* map = &ag->pending.right;
  void* end = assoc_end(map);
  void* found = find_if(map, assoc_front(map), end, &ev,
                        same_pending_event);
  if (found != end)
    return;

  long const wait_ms = 3000;""",
    ),
)

changes["src/lib/ep/e2ap_ep.c"] = (
    (
        "  struct sctp_assoc_change dst = {.sac_state = src->sac_state};",
        "  struct sctp_assoc_change dst = *src;",
    ),
)

# Level-triggered Agent events for single-message SCTP reads
changes["src/agent/asio_agent.c"] = (
    (
        "  const int e_events = EPOLLIN | EPOLLET; // open for reading and edge triggered instead of level triggered",
        "  const int e_events = EPOLLIN; // Keep unread SCTP messages ready for the next iteration",
    ),
)

addition = """
void save_subscription_act_proc(act_proc_t* proc, uint16_t request_id,
                                const ric_subscription_request_t* request)
{
  assert(proc != NULL);
  assert(request != NULL);
  lock_guard(&proc->mtx);

  void* it = assoc_reg_front(&proc->reg);
  void* end = assoc_reg_end(&proc->reg);
  it = find_reg(&proc->reg, it, end, request_id);
  assert(it != end);

  act_proc_val_t* value = assoc_reg_value(&proc->reg, it);
  assert(value->type == RIC_SUBSCRIPTION_PROCEDURE_ACTIVE);
  assert(value->saved_subscription == NULL);
  value->saved_subscription = malloc(sizeof(*value->saved_subscription));
  assert(value->saved_subscription != NULL);
  *value->saved_subscription = copy_subscription_request_xapp(request);
}
"""

# Validate every anchor before writing any source file.
prepared = {}
for relative, replacements in changes.items():
    path = target / relative
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if text.count(old) != 1:
            raise SystemExit(f"Source mismatch: {relative}: {old!r}")
        text = text.replace(old, new, 1)
    if relative == "src/xApp/act_proc.c":
        text = text.rstrip() + "\n\n" + addition.strip() + "\n"
    prepared[path] = text

destination.write_text(header, encoding="utf-8")
for path, text in prepared.items():
    path.write_text(text, encoding="utf-8")
    print(f"Patched container source: {path}", flush=True)
