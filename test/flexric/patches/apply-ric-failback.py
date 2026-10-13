#!/usr/bin/env python3
"""Apply experimental proactive failback only to the Docker source copy."""

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply-ric-failback.py /src/flexric")
root = Path(sys.argv[1]).resolve()
if root != Path("/src/flexric") or not root.is_dir():
    raise SystemExit("Only the Docker source copy /src/flexric is allowed.")

header = root / "src/agent/ric_failback_test.h"
if header.exists():
    raise SystemExit("Failback helper already exists; no changes saved.")

helper = r"""
#ifndef RIC_FAILBACK_TEST_H
#define RIC_FAILBACK_TEST_H

#include <errno.h>
#include <poll.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/sctp.h>
#include <sys/socket.h>
#include "gen_msg_agent.h"

/* Native Emulator experiment: one Agent per process, event-loop owned. */
static struct {
  bool initialized;
  bool enabled;
  char primary[16];
  int probe_fd;
  unsigned successes;
  long long next_probe_ms;
  long long probe_deadline_ms;
} failback_test = {.probe_fd = -1};

static long long failback_now_ms(void)
{
  struct timespec now;
  if(clock_gettime(CLOCK_MONOTONIC, &now) != 0)
    abort();
  return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static void failback_close_probe(void)
{
  if(failback_test.probe_fd >= 0) {
    close(failback_test.probe_fd);
    failback_test.probe_fd = -1;
  }
}

static void failback_probe_result(bool successful, long long now)
{
  failback_close_probe();
  if(successful)
    ++failback_test.successes;
  else
    failback_test.successes = 0;
  failback_test.next_probe_ms = now + 5000;
  if(successful)
    printf("[RIC-FAILBACK]: primary transport probe confirmed %u/3\n",
           failback_test.successes);
}

static void failback_tick(e2_agent_t* ag)
{
  if(!failback_test.initialized) {
    failback_test.initialized = true;
    failback_test.probe_fd = -1;
    char const* enabled = getenv("RIC_FAILBACK_TEST");
    failback_test.enabled = enabled != NULL && strcmp(enabled, "1") == 0;
    if(!failback_test.enabled)
      return;
#ifdef PROXY_AGENT
#error "Proactive failback experiment supports native Emulator only"
#endif
    char const* backup = getenv("RIC_BACKUP_IP");
    struct in_addr address;
    if(backup == NULL || inet_pton(AF_INET, backup, &address) != 1
        || strcmp(backup, ag->ep.base.addr) == 0) {
      fprintf(stderr, "[RIC-FAILBACK]: invalid backup configuration\n");
      abort();
    }
    snprintf(failback_test.primary, sizeof(failback_test.primary),
             "%s", ag->ep.base.addr);
    printf("[RIC-FAILBACK]: enabled; primary=%s; interval=5000 ms; confirmations=3\n",
           failback_test.primary);
  }
  if(!failback_test.enabled)
    return;

  long long now = failback_now_ms();
  if(strcmp(ag->ep.base.addr, failback_test.primary) == 0
      || bi_map_size(&ag->pending) != 0) {
    failback_close_probe();
    failback_test.successes = 0;
    failback_test.next_probe_ms = now + 5000;
    return;
  }

  if(failback_test.probe_fd >= 0) {
    struct pollfd descriptor = {
      .fd = failback_test.probe_fd,
      .events = POLLOUT
    };
    int ready = poll(&descriptor, 1, 0);
    if(ready < 0 && errno == EINTR)
      return;
    if(ready < 0) {
      failback_probe_result(false, now);
      return;
    }
    if(ready > 0) {
      int error = 0;
      socklen_t error_length = sizeof(error);
      struct sctp_status status = {0};
      socklen_t status_length = sizeof(status);
      bool successful =
          (descriptor.revents & POLLOUT) != 0
          && (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) == 0
          && getsockopt(descriptor.fd, SOL_SOCKET, SO_ERROR,
                        &error, &error_length) == 0
          && error == 0
          && getsockopt(descriptor.fd, IPPROTO_SCTP, SCTP_STATUS,
                        &status, &status_length) == 0
          && status.sstat_state == SCTP_ESTABLISHED;
      failback_probe_result(successful, now);
    } else if(now >= failback_test.probe_deadline_ms) {
      failback_probe_result(false, now);
    } else {
      return;
    }
  }

  if(failback_test.successes >= 3) {
    printf("[RIC-FAILBACK]: requesting proactive return to %s\n",
           failback_test.primary);
    failback_test.successes = 0;
    failback_test.next_probe_ms = now + 30000;

    /* Reuse the guarded Setup timer creation, then replace the endpoint.
       The synthetic notification is local; no packet is fabricated. */
    union sctp_notification notification = {0};
    notification.sn_header.sn_type = SCTP_SHUTDOWN_EVENT;
    sctp_msg_t disconnected = {
      .type = SCTP_MSG_NOTIFICATION,
      .notif = &notification
    };
    notification_handle_ag(ag, &disconnected);
    ric_failover_rotate_ag(ag);
    if(strcmp(ag->ep.base.addr, failback_test.primary) != 0)
      abort();

    /* Send immediately: a later Setup timeout can fall back to backup. */
    e2_setup_request_t request = gen_setup_request(&ag->ap.version.type, ag);
    byte_array_t bytes = e2ap_enc_setup_request_ag(&ag->ap, &request);
    e2ap_send_bytes_agent(&ag->ep, bytes);
    free_byte_array(bytes);
    e2ap_free_setup_request(&request);
    return;
  }

  if(failback_test.probe_fd >= 0 || now < failback_test.next_probe_ms)
    return;

  int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC,
                  IPPROTO_SCTP);
  if(fd < 0) {
    failback_probe_result(false, now);
    return;
  }
  failback_test.probe_fd = fd;
  struct sockaddr_in address = {
    .sin_family = AF_INET,
    .sin_port = htons(ag->ep.base.port)
  };
  if(inet_pton(AF_INET, failback_test.primary, &address.sin_addr) != 1)
    abort();
  failback_test.probe_deadline_ms = now + 2000;
  int result = connect(fd, (struct sockaddr*)&address, sizeof(address));
  if(result != 0 && errno != EINPROGRESS && errno != EALREADY
      && errno != EWOULDBLOCK)
    failback_probe_result(false, now);
}

#endif
"""

source = root / "src/agent/e2_agent.c"
text = source.read_text(encoding="utf-8")
changes = (
    (
        "#include <stdio.h>",
        '#include <stdio.h>\n#include "ric_failback_test.h"',
    ),
    (
        "  while(ag->stop_token == false){",
        "  while(ag->stop_token == false){\n    failback_tick(ag);",
    ),
    (
        '  printf("ag->agent_stopped = true \\n");',
        '  failback_close_probe();\n  printf("ag->agent_stopped = true \\n");',
    ),
)
for old, new in changes:
    if text.count(old) != 1:
        raise SystemExit(f"Unexpected source anchor: {old!r}; no changes saved.")
    text = text.replace(old, new, 1)

header.write_text(helper.lstrip(), encoding="utf-8")
source.write_text(text, encoding="utf-8")
print("Applied: src/agent/ric_failback_test.h")
print("Applied: src/agent/e2_agent.c")
