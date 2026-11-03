# Multi-Agent slicing control: OCUDU validation

## Status and scope

**Passed within the offline scheduler/configuration and single-UE online
DL/UL slice-control scopes described below.**

The parent test-case name remains **Multi-Agent slicing control**.
These results establish prerequisites and a working cell-level control path.
They do not establish multi-Agent coordination.

Validated components:

- 29 existing slice scheduler/repository tests.
- 8 selected multi-UE slice budget and reconfiguration tests.
- Baseline and two-slice configuration acceptance, plus rejection of an
  invalid minimum/maximum ratio.
- Offline aggregate-counter recalculation and DL grant review around a
  scheduler reconfiguration.
- Single-cell, single-UE online DL cap reduction and restoration over
  the OCUDU WebSocket remote-control interface.
- Three fresh-container regression rounds through the final unified
  runner using published, digest-pinned image references.
- Four incorrect-evidence checks in each final regression round.

Online UL cap effectiveness passed for the bounded TCP/UDP experiments
below. Online competition between slices or UEs, multi-Agent arbitration,
E2 RC slice-control execution, sustained-load performance and physical RF
remain unvalidated.

## Interface audit

Startup slice configuration uses `cell_cfg.slicing`, with SST, optional SD
and `sched_cfg` PRB policy ratios.

The online experiment uses `rrm_policy_ratio_set` over a text WebSocket
connection to `ws://127.0.0.1:8001/`. A request contains top-level `cmd`
and `policies` fields. Policies identify existing members by PLMN and
S-NSSAI.

This cell-level path updates shared scheduler slice configuration.
The audited E2 DU Style 2 / Action 6 path configures UE grant limits;
it must not be treated as equivalent evidence of shared slice-budget control.

The remote command is not cell-addressed in the audited implementation:
it is forwarded to active cells and updates matching existing policy members.
The online validator therefore uses an independent, single-cell test gNB.

A successful command reply alone does not prove scheduler execution.
The test separately checks the scheduler update event and actual DL grants.

## Online setup and acceptance

The test reuses the existing Open5GS core and starts its own OCUDU gNB and
OAI UE through:

- `deploy/ocudu/compose.zmq.yaml`
- `deploy/ocudu/compose.slice-online.yaml`

The generated configuration disables E2, configures SST 1 without SD,
starts at minimum 0% / maximum 100%, and enables MAC/SCHED debug logs.

Remote control binds to the gNB container's loopback address.
The client joins that container's network namespace; no host control port
is published.

The validator refuses startup if laboratory addresses `172.22.0.160` or
`172.22.0.161` are already occupied. A unique Compose project isolates
container ownership, but does not make these fixed addresses concurrent-safe.

Each online round performs:

1. Pinned image checks and full configuration validation.
2. UE tunnel establishment and five baseline UPF pings.
3. One maximum-ratio reduction request, from 100% to 20%.
4. A successful response, exactly one scheduler slice-update event,
   and five UPF pings.
5. One restoration request to 100%, with the same checks.
6. Test-process and existing baseline-container identity checks.
7. Evidence collection and removal of test-owned containers.
8. Offline DL grant review and four in-memory negative checks.

The core and baseline RIC are not restarted or reconfigured by this test.
Identity continuity is checked; it is not a comprehensive health audit.

## Observed DL grant behavior

For the 51-PRB cell, the 20% maximum becomes 10 PRBs after integer conversion.

| Phase | Maximum configured ratio | Observed DL allocation |
|---|---:|---|
| Limited | 20% | At most 10 PRBs per active DL slot, with the cap reached |
| Restored | 100% | Allocations above the previous 10-PRB cap observed |

The reviewer checks the complete post-update phase windows, matches logged
PDSCH/PUSCH counts to UE records, verifies UE identity and RB intervals,
requires new transmissions, and restricts the reviewed DL logical channel
to LCID 4. DL grants are summed per logged slot.

This is a bounded ping-traffic experiment. It does not measure saturated
slice throughput or demonstrate allocation of the entire 51-PRB cell.
UL grants were observed, but did not exercise the former cap.

Negative checks must reject the intended condition with the expected reason:

- Missing scheduler update.
- DL allocation exceeding the limited cap.
- Restoration with no allocation above the former cap.
- Unexpected DL logical channel.

Mutations affect only in-memory copies of the post-control logs.

## Online UL cap effectiveness

This is a separate validation item under the existing parent test case.
It does not establish multi-Agent coordination.

The experiment retains one cell, one UE, SST 1 without SD and E2 disabled.
It uses the same WebSocket ratio changes: 100% to 20%, then back to 100%.
For the 51-PRB cell, the limited maximum is 10 PRBs.

The load setup adds `compose.slice-ul-load.yaml` for TCP experiments.
The final timed UDP setup instead adds `compose.slice-ul-drain.yaml`
after `compose.zmq.yaml` and `compose.slice-online.yaml`.
A dedicated traffic container uses `172.22.0.151`, with a container-local
route through the existing UPF. Address guards cover the traffic endpoint
as well as the gNB and UE. No host ports are published.

TCP uses a 10 Mbit/s target and a six-second sending duration.
UDP uses a 10 Mbit/s offered rate, 1200-byte datagrams and the original
six-second sending duration. Receiver completion may take much longer
because queued traffic continues through the constrained radio path.
These are bounded functional experiments, not sustained-load benchmarks.

### UDP completion and accounting corrections

The original iperf3 3.16 timed UDP experiment failed with a closed control
connection and a server `Bad file descriptor` error. Source inspection
identified a server protection timer of duration plus 40 seconds.
A byte-count comparison completed with matching send/receive totals;
the limited receiver needed about 76 seconds for approximately 7.5 MB.

A laboratory traffic image builds source package `iperf3=3.16-1build2`.
Its Docker-only patches provide:

- `LAB_IPERF_SERVER_GRACE_SECONDS=180`, extending the completion grace
  while retaining a bounded server timer.
- `LAB_IPERF_UDP_DRAIN=1`, allowing UDP accounting during `TEST_END`
  and waiting for 500 ms of stable receive counts, with at most 500
  ten-millisecond polling waits before final statistics.

The unmodified grace default remains 40 seconds and drain is opt-in.
The validator checks activation markers, requires the quiet interval,
and retains strict equality of sender, server receiver and echoed receiver
byte counts, with zero reported UDP packet loss.
Quiet detection alone does not prove complete delivery.
The tested image is a laboratory correction for this workload; no general
iperf3 concurrency, timeout or loss-accounting fix is claimed.

Docker stdout and stderr histories are retained and checked separately.
Concatenating complete stdout and stderr snapshots previously caused a
false history-change failure when subsequent JSON output was added.

### UL scheduling evidence and regressions

The reviewers match PUSCH header counts to parsed grants, check UE/RNTI,
RB intervals and new transmissions, and sum widths per logged UL slot.
The limited phase must reach 10 PRBs without exceeding it.
Baseline and restored phases must contain allocations above 10 PRBs.

| UDP round | Limited active UL slots | Slots at 10 PRBs | Slots above 10 PRBs | Restored maximum |
|---|---:|---:|---:|---:|
| 1 | 6638 | 3695 | 0 | 51 |
| 2 | 6638 | 3693 | 0 | 51 |
| 3 | 6637 | 3699 | 0 | 51 |

Three independent TCP rounds also passed online execution and UL grant
review. Three final local-reference UDP rounds and a separate published
Docker Hub reference/Compose run passed. Each UDP round checked three
load phases, two control replies and scheduler updates, five UPF pings
per controlled phase, unchanged process identities and test-only cleanup.

Five in-memory negative checks per reviewed UDP run reject an exceeded
cap, missing restoration, inconsistent receiver bytes, missing grace
marker and a drain that did not reach a quiet interval.

| Validation | Evidence directory or report |
|---|---|
| TCP round 1 | `ocudu-slice-online-ul-tcp-4l_fszgn` |
| TCP round 2 | `ocudu-slice-online-ul-tcp-3x7z6hqz` |
| TCP round 3 | `ocudu-slice-online-ul-tcp-xrsszkig` |
| UDP round 1 | `ocudu-slice-online-ul-drain-8qonktn2` |
| UDP round 2 | `ocudu-slice-online-ul-drain-u0x62md6` |
| UDP round 3 | `ocudu-slice-online-ul-drain-ad6inqrn` |
| UDP three-round review | `ocudu-slice-udp-regression-7ryg60_l/summary.json` |
| Published-reference UDP run | `ocudu-slice-online-ul-drain-xadw8l91` |
| Published-reference combined review | `ocudu-slice-udp-regression-sp2o0gli/summary.json` |

Run the final timed UDP online test, then review its printed evidence path:

```bash
python3 -B test/ocudu/validate-slice-online-ul-drain.py
python3 -B test/ocudu/validate-slice-online-udp-regression.py \
  --evidence /absolute/path/to/retained-udp-run
```

The regression reviewer reads retained evidence and performs negative checks;
it does not launch online rounds. Standalone
`review-slice-online-udp-grants.py` writes `online-udp-grant-review.json`
exclusively. The regression reviewer can repeat reviews without overwriting
that file.

TCP entry points are `validate-slice-online-ul-tcp.py` and
`review-slice-online-ul-grants.py`. Original UDP, byte-count and grace-only
scripts remain diagnostic history, not the final UDP acceptance path.
Live summaries retain false grant-review flags; use the separate combined
review report for UL cap acceptance.

The final traffic image reference is:

```text
limx59/oai-pi-ocudu-slice-udp-traffic:arm64-iperf316-server-drain-test@sha256:6146f02626b1a5157552ed9be9afdfc92a2746fb5c33b38051c8aa80172a9904
```

Build definitions are `Dockerfile.slice-udp-traffic-drain` and its required
patches `patch-iperf3-server-grace.py` and `patch-iperf3-server-drain.py`.
The grace-only image is retained as an intermediate diagnostic version.
Host third-party source and the existing UE runtime image remain unchanged.

## Configuration checker

The original gNB `--dryrun` exits before semantic configuration validation.
It must not be used to claim that an invalid ratio has been rejected.

The laboratory checker applies
`patches/patch-ocudu-validated-dryrun.py` inside its Docker build copy.
It runs the existing configuration validators before exiting, and emits
`LAB_CONFIG_VALIDATION_PASSED` only for accepted configurations.

The invalid 80% minimum / 40% maximum scenario must exit with the expected
validation diagnostic. That error is the expected negative-test result.

The checker is a laboratory tool, not the online gNB runtime image.
Host third-party source trees remain unchanged.

## Image references

The scripts use published ARM64 images with fixed digests.

| Component | Docker Hub tag | Digest |
|---|---|---|
| Scheduler tests | `limx59/oai-pi-ocudu-scheduler-tests:arm64-slicing-test` | `sha256:a6432f1ea245d94dc8f14b8325034feef36bef66ab142413d6489525f6b0b4cb` |
| Configuration checker | `limx59/oai-pi-ocudu-config-check:arm64-slicing-test` | `sha256:2e750f07d68d00cdf2bdc34c9bfc28f2928e70ea393cbf17b137d218dc063186` |
| WebSocket client | `limx59/oai-pi-ocudu-slice-control-client:arm64-rrm-policy-ratio-ws-client-test` | `sha256:6b9a231faec61a643b68582ae69701ce3e8da2e14ea62b829cc6325c27efb40e` |
| Online gNB | `limx59/oai-pi-ocudu-gnb:arm64-steering-prb-kpm-metadata-v2-test` | `sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b` |
| Online UE | `limx59/oai-pi-oai-nr-ue:arm64-zmq-dci10-config-selection-test` | `sha256:bbdceed41714844717eaf9a06e09284f5404e27daff870d1f1ec08c782182047` |

Images must already be available locally. The tests do not build or
automatically pull them.

## Run the tests

From the repository root, run the isolated offline tests:

```bash
python3 -B test/ocudu/validate-slice-scheduler.py
python3 -B test/ocudu/validate-multi-slice-scheduler.py
python3 -B test/ocudu/validate-slice-startup-v2.py
```

The online test additionally requires the existing core network,
subscriber configuration, private `deploy/ocudu/.local/ue-zmq.conf`,
UE capability XML and `/dev/net/tun`. Do not print or commit subscriber secrets.

Run three online rounds, grant reviews and negative checks:

```bash
python3 -B test/ocudu/validate-slice-online-regression.py --rounds 3
```

For one online control/connectivity run without automatic grant review:

```bash
python3 -B test/ocudu/validate-slice-online-control.py
```

Review a retained run:

```bash
python3 -B test/ocudu/review-slice-online-grants.py \
  --evidence /absolute/path/to/retained-run
```

That reviewer creates `online-grant-review.json` exclusively and refuses to
overwrite it. Use the regression runner's retained-evidence mode to repeat
reviews without modifying the original evidence:

```bash
python3 -B test/ocudu/validate-slice-online-regression.py \
  --evidence /absolute/path/to/retained-run
```

Evidence paths must be under this repository's
`test/ocudu/.local/evidence` directory.

## Evidence and result interpretation

| Validation | Retained evidence directory | Result |
|---|---|---|
| Slice scheduler | `ocudu-slice-scheduler-lcar4_mr` | 29 tests passed |
| Multi-slice scheduler | `ocudu-multi-slice-scheduler-t1vwsrc2` | 8 tests passed |
| Configuration validation | `ocudu-slice-startup-v2-donxu24w` | 3 scenarios passed |
| Published-reference online round 1 | `ocudu-slice-online-control-n2eaz5a8` | Control, grants and negative checks passed |
| Published-reference online round 2 | `ocudu-slice-online-control-r8729b1r` | Control, grants and negative checks passed |
| Published-reference online round 3 | `ocudu-slice-online-control-l3ht_pn3` | Control, grants and negative checks passed |

The final published-reference regression report is
`ocudu-slice-regression-3whcpz1m/summary.json`.
Earlier unified local-image regression report:
`ocudu-slice-regression-b0f3clx2/summary.json`.

Online `summary.json` covers control execution and connectivity.
Its `raw_grant_limits_validated` field remains false because grant
validation is performed separately. Use the unified regression report,
which embeds the grant review and negative-check results, for combined
acceptance. Do not interpret a preparation helper's scope flags as live
test results.

Evidence is retained privately under `.local/evidence`; do not commit
runtime logs, generated private configurations or subscriber data.

## Scripts and build files

The maintained entry points are:

- `validate-slice-scheduler.py`
- `validate-multi-slice-scheduler.py`
- `validate-slice-startup-v2.py`
- `prepare-slice-startup.py`
- `prepare-slice-online.py`
- `slice-control-client.py`
- `validate-slice-online-control.py`
- `review-slice-online-grants.py`
- `validate-slice-online-regression.py`
- `review-slice-scheduler-evidence.py`
- `review-slice-reconfiguration-grants.py`

Build definitions are under `docker/ocudu`:

- `Dockerfile.slice-scheduler-test`
- `Dockerfile.slice-config-check`
- `Dockerfile.slice-control-client`

## Remaining scope

Multi-Agent coordination remains open as the next separate validation item.
Online UL cap effectiveness is complete within the bounded single-UE
TCP/UDP scope documented above.
The online experiment uses one UE and one configured data slice through
WebSocket control; it does not validate E2 RC control, multiple competing
online slices, Agent policy conflict resolution, or physical RF.

The original OAI standalone PRB-cap simulation remains a separate baseline;
see [the existing FlexRIC test documentation](../flexric/README.md).
