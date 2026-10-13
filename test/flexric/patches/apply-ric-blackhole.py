#!/usr/bin/env python3
"""Apply opt-in SCTP socket settings only to the Docker source copy."""

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply-ric-blackhole.py /src/flexric")
root = Path(sys.argv[1]).resolve()
if root != Path("/src/flexric") or not root.is_dir():
    raise SystemExit("Only /src/flexric inside the build is allowed.")

p = root / "src/agent/endpoint_agent.c"
text = p.read_text(encoding="utf-8")
anchor = "  ep->to = servaddr;"
if text.count(anchor) != 1:
    raise SystemExit("Unexpected socket initialization; no changes saved.")

addition = r"""
  /* Experimental per-socket settings; never change host sysctls. */
  char const* blackhole_test = getenv("RIC_BLACKHOLE_TEST");
  if(blackhole_test != NULL && strcmp(blackhole_test, "1") == 0) {
    struct sctp_rtoinfo rto = {0};
    rto.srto_initial = 1000;
    rto.srto_min = 1000;
    rto.srto_max = 2000;
    if(setsockopt(sock_fd, IPPROTO_SCTP, SCTP_RTOINFO,
                  &rto, sizeof(rto)) != 0) {
      perror("[RIC-BLACKHOLE]: SCTP_RTOINFO");
      abort();
    }

    struct sctp_assocparams assoc = {0};
    assoc.sasoc_asocmaxrxt = 3;
    if(setsockopt(sock_fd, IPPROTO_SCTP, SCTP_ASSOCINFO,
                  &assoc, sizeof(assoc)) != 0) {
      perror("[RIC-BLACKHOLE]: SCTP_ASSOCINFO");
      abort();
    }

    socklen_t rto_len = sizeof(rto);
    socklen_t assoc_len = sizeof(assoc);
    if(getsockopt(sock_fd, IPPROTO_SCTP, SCTP_RTOINFO,
                  &rto, &rto_len) != 0 ||
       getsockopt(sock_fd, IPPROTO_SCTP, SCTP_ASSOCINFO,
                  &assoc, &assoc_len) != 0) {
      perror("[RIC-BLACKHOLE]: socket verification");
      abort();
    }
    if(rto.srto_initial != 1000 || rto.srto_min != 1000 ||
       rto.srto_max != 2000 || assoc.sasoc_asocmaxrxt != 3) {
      fprintf(stderr, "[RIC-BLACKHOLE]: unexpected socket settings\n");
      abort();
    }
    printf("[RIC-BLACKHOLE]: socket RTO initial=%u min=%u max=%u ms; "
           "association_max_retrans=%u\n",
           (unsigned)rto.srto_initial, (unsigned)rto.srto_min,
           (unsigned)rto.srto_max, (unsigned)assoc.sasoc_asocmaxrxt);
  }

"""
p.write_text(text.replace(anchor, addition + anchor, 1), encoding="utf-8")
print("Applied: opt-in Agent socket blackhole experiment")
