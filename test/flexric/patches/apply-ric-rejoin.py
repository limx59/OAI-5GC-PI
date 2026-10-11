#!/usr/bin/env python3
"""Apply experimental RIC rejoin recovery to the Docker source copy."""

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply-ric-rejoin.py /src/flexric")
root = Path(sys.argv[1]).resolve()
if root != Path("/src/flexric") or not root.is_dir():
    raise SystemExit("Only the Docker source copy /src/flexric is allowed.")

prepared = {}


def replace(relative, old, new):
    p = root / relative
    text = prepared.get(p, p.read_text(encoding="utf-8"))
    if text.count(old) != 1:
        raise SystemExit(f"Unexpected source anchor: {relative}; no changes saved.")
    prepared[p] = text.replace(old, new, 1)


replace(
    "src/ric/map_e2_node_sockaddr.h",
    "\n#endif",
    """
/* Returned node IDs are owned by the caller; missing entries return NULL. */
global_e2_node_id_t* ric_rejoin_take_node(
    map_e2_node_sockaddr_t* m, global_e2_node_id_t const* id);
global_e2_node_id_t* ric_rejoin_take_assoc(
    map_e2_node_sockaddr_t* m, sctp_assoc_t association);

#endif""",
)

relative = "src/ric/map_e2_node_sockaddr.c"
source = root / relative
text = source.read_text(encoding="utf-8")
if "ric_rejoin_take_node" in text:
    raise SystemExit("Mapping helpers already present; no changes saved.")

prepared[source] = text + r"""
/* Copy the SCTP key before extraction invalidates the tree entry. */
global_e2_node_id_t* ric_rejoin_take_node(
    map_e2_node_sockaddr_t* m, global_e2_node_id_t const* id)
{
  lock_guard(&m->mtx);
  void* end = assoc_end(&m->map.left);
  void* it = find_if(&m->map.left, assoc_front(&m->map.left),
                    end, (void*)id, eq_global_e2_node_id_wrapper);
  if(it == end)
    return NULL;
  sctp_info_t info = *(sctp_info_t*)assoc_value(&m->map.left, it);
  return bi_map_extract_right(&m->map, &info, sizeof(info), NULL);
}

global_e2_node_id_t* ric_rejoin_take_assoc(
    map_e2_node_sockaddr_t* m, sctp_assoc_t association)
{
  if(association == 0)
    return NULL;
  lock_guard(&m->mtx);
  void* end = assoc_end(&m->map.left);
  for(void* it = assoc_front(&m->map.left);
      it != end; it = assoc_next(&m->map.left, it)) {
    sctp_info_t info = *(sctp_info_t*)assoc_value(&m->map.left, it);
    if(info.sri.sinfo_assoc_id == association)
      return bi_map_extract_right(&m->map, &info, sizeof(info), NULL);
  }
  return NULL;
}
"""


replace(
    "src/ric/near_ric.h",
    "  pthread_mutex_t conn_e2_nodes_mtx;",
    "  pthread_mutex_t conn_e2_nodes_mtx;\n"
    "  pthread_mutex_t rejoin_mtx; /* Serialize E2 state transitions. */",
)

replace(
    "src/ric/near_ric.c",
    "  seq_init(&ric->conn_e2_nodes, sizeof(e2_node_t));",
    """  int rejoin_rc = pthread_mutex_init(&ric->rejoin_mtx, NULL);
  if(rejoin_rc != 0)
    abort();
  seq_init(&ric->conn_e2_nodes, sizeof(e2_node_t));""",
)

replace(
    "src/ric/near_ric.c",
    "  int rc = pthread_mutex_destroy(&ric->conn_e2_nodes_mtx);",
    """  int rejoin_rc = pthread_mutex_destroy(&ric->rejoin_mtx);
  if(rejoin_rc != 0)
    abort();
  int rc = pthread_mutex_destroy(&ric->conn_e2_nodes_mtx);""",
)

replace(
    "src/ric/near_ric.c",
    "  e2ap_msg_t const msg = e2ap_msg_dec_ric(&ric->ap, sctp_msg->ba);",
    """  lock_guard(&ric->rejoin_mtx);
  e2ap_msg_t const msg = e2ap_msg_dec_ric(&ric->ap, sctp_msg->ba);""",
)

replace(
    "src/ric/near_ric.c",
    "            notification_handle_ric(ric, &e.msg);",
    """            lock_guard(&ric->rejoin_mtx);
            notification_handle_ric(ric, &e.msg);""",
)


replace(
    "src/ric/endpoint_ric.c",
    "struct sctp_event_subscribe evnts = {.sctp_data_io_event = 1,",
    "struct sctp_event_subscribe evnts = {.sctp_association_event = 1,\n"
    "                                      .sctp_data_io_event = 1,",
)

replace(
    "src/ric/not_handler_ric.h",
    "void notification_handle_ric",
    "void ric_rejoin_forget_node(near_ric_t* ric, global_e2_node_id_t* id);\n\n"
    "void notification_handle_ric",
)

relative = "src/ric/not_handler_ric.c"
source = root / relative
original = source.read_text(encoding="utf-8")
marker = "void notification_handle_ric(near_ric_t* ric, sctp_msg_t const* msg)"
if original.count(marker) != 1:
    raise SystemExit("Unexpected notification function; no changes saved.")
start = original.index(marker)
old = original[start:]
if ('"Only shutdown event supported"' not in old
        or old.count("rm_e2_node_iapp_api(id);") != 1):
    raise SystemExit("Unexpected notification cleanup; no changes saved.")

replace(relative, old, r"""
/* Caller holds rejoin_mtx; this function consumes the returned mapping ID. */
void ric_rejoin_forget_node(near_ric_t* ric, global_e2_node_id_t* id)
{
  if(id == NULL)
    return;
  defer({free_global_e2_node_id(id); free(id);});
  bool removed = false;
  {
    lock_guard(&ric->conn_e2_nodes_mtx);
    void* end = seq_end(&ric->conn_e2_nodes);
    void* it = find_if(&ric->conn_e2_nodes,
                      seq_front(&ric->conn_e2_nodes), end,
                      id, eq_global_e2_node_id_e2_node);
    if(it != end) {
      free_e2_node((e2_node_t*)it);
      void* next = seq_next(&ric->conn_e2_nodes, it);
      seq_erase(&ric->conn_e2_nodes, it, next);
      removed = true;
    }
  }
  if(removed) {
    rm_e2_node_iapp_api(id);
    printf("[RIC-REJOIN]: old node %u removed\n", id->nb_id.nb_id);
  }
}

void notification_handle_ric(near_ric_t* ric, sctp_msg_t const* msg)
{
  assert(ric != NULL);
  assert(msg != NULL && msg->type == SCTP_MSG_NOTIFICATION);
  sctp_assoc_t association = 0;
  unsigned type = msg->notif->sn_header.sn_type;
  if(type == SCTP_SHUTDOWN_EVENT) {
    association = msg->notif->sn_shutdown_event.sse_assoc_id;
  } else if(type == SCTP_ASSOC_CHANGE) {
    unsigned state = msg->notif->sn_assoc_change.sac_state;
    if(state != SCTP_COMM_LOST && state != SCTP_SHUTDOWN_COMP
        && state != SCTP_CANT_STR_ASSOC && state != SCTP_RESTART)
      return;
    association = msg->notif->sn_assoc_change.sac_assoc_id;
  } else {
    return;
  }
  global_e2_node_id_t* id =
      ric_rejoin_take_assoc(&ric->ep.e2_nodes, association);
  if(id == NULL) {
    printf("[RIC-REJOIN]: ignored unmapped association %d\n",
           (int)association);
    return;
  }
  ric_rejoin_forget_node(ric, id);
}
""")

replace(
    "src/ric/near_ric.c",
    "    e2ap_reg_sock_addr_ric(&ric->ep, id, &sctp_msg->info);",
    """    ric_rejoin_forget_node(ric,
        ric_rejoin_take_node(&ric->ep.e2_nodes, id));
    e2ap_reg_sock_addr_ric(&ric->ep, id, &sctp_msg->info);""",
)

for p, text in prepared.items():
    p.write_text(text, encoding="utf-8")
    print(f"Applied: {p.relative_to(root)}")
