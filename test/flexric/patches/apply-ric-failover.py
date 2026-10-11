#!/usr/bin/env python3
"""Apply experimental RIC failover changes to the container source copy."""

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply-ric-failover.py /src/flexric")
root = Path(sys.argv[1]).resolve()
if root != Path("/src/flexric") or not root.is_dir():
    raise SystemExit("Only the container source copy /src/flexric is allowed.")

prepared = {}


def replace(relative, old, new):
    p = root / relative
    text = prepared.get(p, p.read_text(encoding="utf-8"))
    if text.count(old) != 1:
        raise SystemExit(f"Unexpected source block in {relative}; no changes saved.")
    prepared[p] = text.replace(old, new, 1)





replace(
    "src/agent/not_handler_agent.h",
    "void notification_handle_ag",
    "void ric_failover_rotate_ag(e2_agent_t* ag);\n\nvoid notification_handle_ag",
)

replace(
    "src/agent/msg_handler_agent.c",
    "void init_handle_msg_agent",
    """/* This experiment supports periodic Emulator subscriptions only. */
void ric_failover_clear_subscriptions_ag(e2_agent_t* ag)
{
  while(bi_map_size(&ag->ind_event) != 0) {
    void* it = assoc_rb_tree_front(&ag->ind_event.right);
    ind_event_t* ev = assoc_rb_tree_key(&ag->ind_event.right, it);
    assert(ev->type != APERIODIC_SUBSCRIPTION_FLRC
        && "Failover experiment requires periodic subscriptions");
    ric_gen_id_t id = ev->ric_id;
    bool const stopped = stop_ind_event(ag, id);
    if(!stopped) {
      fprintf(stderr, "[RIC-FAILOVER]: subscription cleanup failed\\n");
      abort();
    }
  }
  printf("[RIC-FAILOVER]: old subscriptions cleared\\n");
}

void init_handle_msg_agent""",
)

replace(
    "src/agent/not_handler_agent.c",
    '#include <stdio.h>',
    """#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include "endpoint_agent.h"

void ric_failover_clear_subscriptions_ag(e2_agent_t* ag);

void ric_failover_rotate_ag(e2_agent_t* ag)
{
  char const* backup = getenv("RIC_BACKUP_IP");
  if(backup == NULL || backup[0] == '\\0')
    return;

#ifdef PROXY_AGENT
#error "This failover experiment supports the native Emulator only"
#endif

  static char primary[16];
  if(primary[0] == '\\0')
    snprintf(primary, sizeof(primary), "%s", ag->ep.base.addr);

  struct in_addr validated;
  assert(inet_pton(AF_INET, backup, &validated) == 1);
  assert(strlen(backup) < sizeof(primary));
  assert(strcmp(primary, backup) != 0);

  char next[16];
  snprintf(next, sizeof(next), "%s",
      strcmp(ag->ep.base.addr, primary) == 0 ? backup : primary);
  int port = ag->ep.base.port;
  printf("[RIC-FAILOVER]: switching %s -> %s\\n", ag->ep.base.addr, next);

  ric_failover_clear_subscriptions_ag(ag);

  /* DEL only: endpoint cleanup owns the socket close. */
  int rc = epoll_ctl(ag->io.efd, EPOLL_CTL_DEL, ag->ep.base.fd, NULL);
  assert(rc == 0);
  e2ap_free_ep_agent(&ag->ep);
  memset(&ag->ep, 0, sizeof(ag->ep));
  e2ap_init_ep_agent(&ag->ep, next, port);
  add_fd_asio_agent(&ag->io, ag->ep.base.fd);
  ag->trans_id_setup_req = 0;
}""",
)

replace(
    'src/agent/not_handler_agent.c',
    '  // A pending event is created along with a timer of 3000 ms,',
    '  char const* backup = getenv("RIC_BACKUP_IP");\n  if(backup != NULL && backup[0] != \'\\0\')\n    ric_failover_clear_subscriptions_ag(ag);\n\n  // A pending event is created along with a timer of 3000 ms,',
)

replace(
    "src/agent/e2_agent.c",
    "          // Resend the setup request message",
    """          /* Alternate configured endpoints after a setup timeout. */
          ric_failover_rotate_ag(ag);

          // Resend the setup request message""",
)


replace(
    "src/agent/msg_handler_agent.c",
    "#include <stdio.h>",
    "#include <stdio.h>\n#include <stdlib.h>",
)

for p, text in prepared.items():
    p.write_text(text, encoding="utf-8")
    print(f"Applied: {p.relative_to(root)}")
