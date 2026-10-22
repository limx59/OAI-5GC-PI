# QoS monitoring

## Validated scope

Validated on the ARM64 Raspberry Pi on 2026-10-21, Pacific time:

- Five DU KPM fields, raw units, normalized values and missing values.
- Separate UL/DL traffic at 1 Mbps, 200 kbps and 1 Mbps.
- Three-report low-throughput alerts and hysteresis-based recovery.
- Persistent supervisor state across two managed SDK sessions.
- Silence detection, session reset and fresh report counters.
- Advisory operation without control requests in the checked logs.
- Three consecutive rounds of both integration cases: six successful runs.

This is a single-UE software-radio experiment. RLC delay and SDU drop
statistics are not end-to-end latency or application packet loss.
Live delay/drop fault injection was not performed; their threshold
transitions were checked with offline inputs.

Low offered load and idle periods can trigger throughput alerts.
An alert does not establish congestion or an SLA violation.
Nominal collection windows are not exact RLC sample boundaries.

## Files

| File | Purpose |
| --- | --- |
| `qos_monitor_state.py` | Units, thresholds, per-key state and session generations |
| `test-qos-monitor-state.py` | Thirteen offline state tests |
| `xapp-qos-monitor.py` | SDK callback, CSV and advisory events |
| `validate-qos-monitor.py` | Five-field and UL/DL traffic validation |
| `qos_recovery_stream.py` | Persistent supervisor reading separate session CSV files |
| `validate-qos-recovery.py` | Managed SDK reconnection and UL state recovery |
| `qos_startup_guard.py` | Bounded host I/O readiness check |
| `test-qos-startup-guard.py` | Three offline readiness tests |
| `validate-qos-regression.py` | Serial repetition, source snapshots and host diagnostics |

The successful CSV metadata and UE identity cases remain separate.

## Prerequisites and images

Use the existing Open5GS deployment, private UE configuration and
`docker_open5gs_default` network described in
[the CSV metadata guide](README.kpm-csv-metadata.md).

Keep the shared core and baseline RIC running. Stop the experimental
gNB and UE before testing. Run one experiment at a time.

Required existing image tags:

```txt
limx59/oai-pi-ocudu-flexric-ric:arm64-kpm-csv-metadata-test
limx59/oai-pi-ocudu-flexric-xapp:arm64-kpm-csv-metadata-test
limx59/oai-pi-ocudu-gnb:arm64-kpm-collection-clock
limx59/oai-pi-oai-nr-ue:arm64-zmq-test
```

The metadata RIC/xApp tags were previously published and pull-verified.
This QoS work reuses them; it does not publish new images.
Python files are copied into the evidence directory and mounted into
the SDK container. The supervisor runs on the host.

The scripts create a temporary RIC at `172.22.0.163`, use the experimental
gNB/UE and create a traffic endpoint at `172.22.0.151`.
The baseline RIC at `172.22.0.162` remains running.

The scripts use the existing Compose combination plus a temporary
override. No persistent Compose modification is required.
On exit they remove temporary containers, restore the original RAN
configuration and leave the experimental gNB/UE stopped.

## Units and experimental thresholds

| Metric | Raw unit | Normalized unit | Alert condition | Clear condition |
| --- | --- | --- | --- | --- |
| `DRB.UEThpDl` | kbps | bit/s, multiply by 1000 | below 500000 | at least 800000 |
| `DRB.UEThpUl` | kbps | bit/s, multiply by 1000 | below 500000 | at least 800000 |
| `DRB.RlcSduDelayDl` | 0.1 ms | ms, multiply by 0.1 | above 50 | at most 40 |
| `DRB.RlcDelayUl` | 0.1 ms | ms, multiply by 0.1 | above 50 | at most 40 |
| `DRB.RlcPacketDropRateDl` | percent | percent | above 5 | at most 2 |

Alert and recovery require three consecutive qualifying reports.
Duplicate/out-of-order reports do not advance counters. Missing or
incomplete values break streaks; they are not converted into zero.
The silence timeout is five seconds.

These are experimental thresholds, not commercial SLA criteria.

## Offline checks

```bash
python3 -B ~/Work/oai-5gc-pi-review/test/ocudu/test-qos-monitor-state.py
python3 -B ~/Work/oai-5gc-pi-review/test/ocudu/test-qos-startup-guard.py
```

The SDK callback was additionally checked with constructed five-metric
reports. The recovery adapter was checked by replaying retained real
CSV rows. Those checks do not substitute for live subscriptions.

## Individual integration cases

Five-field recording and directional high/low/high traffic:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  ~/Work/oai-5gc-pi-review/test/ocudu/validate-qos-monitor.py \
  </dev/null
```

Persistent supervisor across two managed SDK sessions:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  ~/Work/oai-5gc-pi-review/test/ocudu/validate-qos-recovery.py \
  </dev/null
```

Recovery means normal SDK-session shutdown followed by a new SDK
process connecting and subscribing. The supervisor remains alive;
the test RIC, gNB and UE keep their process identities.

The new session starts at report 1, reaches ALERT on report 3, and
recovers after three consecutive high-throughput reports.
Old-generation rejection is checked by explicitly replaying a retained
row. Real delayed-packet injection, same-process automatic reconnection,
RIC restart and Agent restart are outside this case.

A new session can become STALE before its first report if startup takes
over five seconds. The first valid report then produces REPORT_RESUMED.
Idle after traffic can trigger another low-throughput alert.

## Three-round regression

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  ~/Work/oai-5gc-pi-review/test/ocudu/validate-qos-regression.py \
  --rounds 3 </dev/null
```

Each round runs monitoring followed by recovery. The runner stops on
the first failure without automatic retries or core restarts.
It saves source hashes/snapshots, validator output and timestamped
vmstat samples. On validator failure it attempts to collect filtered,
redacted core error logs.

The current runner first checks host readiness: up to 30 seconds,
requiring three consecutive approximately one-second samples with
I/O wait below 50% and fewer than 16 blocked tasks.
These are experimental guard limits, not hardware health certification.

The guard checks the host only. It cannot verify AUSF business routing
or prevent I/O contention that begins after RAN startup.
Direct invocation of an individual case does not use this guard.

The three-round integration result below predates guard integration.
The two underlying integration cases were unchanged. The guard itself
passed one real read-only check and three offline behavioral tests;
the complete six-run sequence was not repeated after wiring it in.

## Results and evidence

Evidence root on the Raspberry Pi: `~/Work/oai-test-evidence/`.

Initial monitoring pass: `ocudu-qos-monitor-nmcbi5v_`:

- 110 reports, 550 rows, no callback or cleanup errors.
- Six traffic phases; KPM/iperf ratios approximately 1.028–1.041.
- Application receiver packet loss was zero.
- Valid delay values were intermittent: DL 41 rows, UL 43 rows.
  Missing/incomplete delay rows were retained explicitly.

Initial recovery pass: `ocudu-qos-recovery-a96811l1`:

- SDK xApp IDs 7 and 8; session generations 1 and 2.
- Seven reports in session 1 and 35 in session 2.
- Fresh counters 1, 2, 3; recovery after three high reports.
- Application receiver approximately 994 kbps, zero packet loss.

Three-round summary: `ocudu-qos-regression-nywgp437`.

| Round | Monitoring evidence suffix | Recovery evidence suffix |
| --- | --- | --- |
| 1 | `6hg5mjng` | `hkxph3sc` |
| 2 | `8129hqri` | `il6hn62d` |
| 3 | `rgh2icqk` | `hp6f1iwp` |

Use prefixes `ocudu-qos-monitor-` and `ocudu-qos-recovery-`.
All six cases passed with exit 0 and empty cleanup errors.
The baseline RIC remained unchanged; each case restored and stopped
the experimental RAN.

`host-resource-review.json` records I/O wait maxima of
36%, 44%, 21%, 20%, 7% and 10%, respectively. No interval sample
reached 50%. These are whole-case statistics, including cleanup.
They support repeatability within this run, not long-term stability.

Readiness evidence: `ocudu-qos-startup-guard-s3z2m6ma`.
The pre-guard regression runner was retained under
`ocudu-qos-guard-integration-w6ousss9`.

## Core-network failure and recovery

Retain failed evidence:

- `ocudu-qos-monitor-jdwrakw7`: Docker inspect timeout before UE TUN;
  multiple NF heartbeat losses and SBI timeout; registration reject 90.
- `ocudu-qos-monitor-5dyz3hgu`: UE registration failure, reject 9.
- `ocudu-qos-host-monitor-q2noni9p`: synchronous host monitoring.

The monitored failure had approximately 75%–96% I/O wait and up to
64 blocked tasks before UE registration. Swap-in/out was zero during
those samples. Multiple core functions lost heartbeats.

The decisive routing evidence was:

```txt
SCP: NF EndPoint(addr) setup [172.22.0.13:0]
SCP: Failed to connect to 172.22.0.13 port 80: Connection refused
SCP: response_handler() failed [-1]
AUSF: HTTP response error [500]
AMF: Registration reject [9]
```

AUSF had already automatically re-registered before the failed
authentication. This does not support an explanation that idle AUSF
normally sleeps and requires restart to register.

After these specific symptoms were identified, only AUSF was restarted.
The next monitoring case, recovery case and all six regression cases
passed using unchanged integration scripts and images.

This is an observed recovery procedure, not a proven root-cause fix.
The origin of the incorrect target port and its causal relationship
to host I/O contention remain unresolved.
A `:80` profile setup log alone is insufficient: successful historical
runs also contained such logs. Actual refused connections matter.

Do not add routine AUSF restarts to the test scripts.
Preserve the failed run and correlate its timestamps before recovery.
NRF registration success alone does not establish working authentication
routing. Earlier incidents required different recovery sequences.

## Archival status

The tested runtime images are reused. No new image publication or
persistent Compose change is required for these Python tests.
Repository index/TODO updates, final checks and Git delivery are
recorded separately; this guide does not imply they are complete.
