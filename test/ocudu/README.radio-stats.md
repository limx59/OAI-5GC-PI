# MAC / RLC / PDCP statistics

## Validation status

Validated on the ARM64 Raspberry Pi through 2026-10-22, Pacific time.

The DU statistics case and CU-UP PDCP metrics-clock case each passed
three consecutive runs, six integration runs total. All six runs reported
no cleanup errors and retained the baseline RIC identity.

This validates the documented single-UE software-radio subset.
Source-counter reset handling, one-to-one KPM/source-batch correlation,
independent scheduler accuracy and complete MAC/RLC/PDCP coverage remain
unvalidated.

## Measurements and interpretation

| Measurement | Raw unit | Interpretation |
| --- | --- | --- |
| `RRU.PrbAvailDl`, `RRU.PrbAvailUl` | PRB | Cell availability, including in UE reports |
| `RRU.PrbUsedDl`, `RRU.PrbUsedUl` | PRB | Integer mean PRBs per corresponding slot |
| `RRU.PrbTotDl`, `RRU.PrbTotUl` | percent | Integer utilization derived from the provider's integer mean |
| `DRB.RlcSduTransmittedVolumeDL`, `DRB.RlcSduTransmittedVolumeUL` | kbit | Cached SDU batch volume, not a lifetime cumulative counter |
| `DRB.UEThpDl`, `DRB.UEThpUl` | kbps | Provider throughput; multiplied by 1000 for bit/s |
| `DRB.PacketSuccessRateUlgNBUu` | percent | CU-UP node-level ratio from cached PDCP RX history |

PRB and volume values are not converted to bit/s. A zero PRB value can
result from integer rounding under low load. Unavailable values remain
empty rather than being replaced with zero.

The PDCP ratio is not application packet loss. RLC volume decreases are
normal for period statistics and do not establish a counter reset.
Collection-header windows are nominal protocol windows, not exact
underlying sample boundaries.

The CU-UP provider's reordering-delay path was reviewed but is not
validated by these scripts. In particular, its zero-delay handling
requires separate investigation.

## Prerequisites and isolation

Run commands from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Follow [the CSV prerequisites](README.kpm-csv-metadata.md) for the existing
Open5GS network, private UE configuration and baseline images.

Keep the shared core and baseline RIC running. Stop the experimental
OCUDU gNB and OAI UE before testing. Do not run concurrent experiments.

The validators use temporary RIC address `172.22.0.163` and traffic
endpoint `172.22.0.151`; both must be available. The baseline RIC remains
at `172.22.0.162`.

Validators create the experimental containers, collect evidence, remove
temporary services, and restore the original RAN configuration stopped.
Review cleanup errors after any failed or interrupted run before retrying.
The regression wrapper stops on the first failed case.

The host startup guard checks bounded host I/O readiness. It is not an
AUSF/SBI health check and cannot prevent contention after RAN startup.
These tests do not automatically restart core network functions.

## Published runtime image

The following ARM64 image was pushed and pulled successfully on
2026-10-22, Pacific time. Its digest matches the three-round PDCP tests.

```bash
sudo docker pull limx59/oai-pi-ocudu-gnb:arm64-kpm-pdcp-metrics-clock-test@sha256:4ac145aa07c430d326a981947a63ec646dad913a21be5cf7441084764ceb8332
```

The DU validator retains the existing `arm64-kpm-collection-clock` gNB
image. Both cases reuse the published FlexRIC RIC/xApp metadata images
and OAI UE image listed in the CSV guide.

The intermediate CU-UP report-clock image and C++ test image were
also pushed and pulled successfully on 2026-10-22, Pacific time.
Their digests match the locally tested images.

```bash
sudo docker pull limx59/oai-pi-ocudu-gnb:arm64-kpm-cu-up-report-clock-test@sha256:1112e8512028aadc3b41e84cf9ca7a35986722b29f82c3b9a55dd703d3186e65
sudo docker pull limx59/oai-pi-ocudu-kpm-tests:arm64-pdcp-metrics-clock-test@sha256:38ab4dccf0ba395df08c85a2cec66628e26d301778796042d28a830597862612
```

## Run the integration cases

DU scheduler PRB and RLC statistics:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/validate-radio-stats.py </dev/null
```

CU-UP PDCP statistics clock, batch progression and KPM delivery:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/validate-pdcp-metrics-clock.py </dev/null
```

Three serial rounds of both cases:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/validate-statistics-regression.py --rounds 3 </dev/null
```

The regression script retains per-run logs, evidence paths, source
checksums and an aggregate summary under `~/Work/oai-test-evidence/`.
Individual validators also retain their own evidence directories.

## Acceptance and observed results

DU acceptance checks include ten fields, units, finite values,
unavailable-value handling, complete metric groups and duplicate exported
CSV keys. Each direction requires at least five nominal interior reports
and a KPM/application receiver-rate ratio between 0.7 and 1.5.
Application receiver throughput must be at least 800 kbit/s with no more
than 5 percent packet loss under the offered 1 Mbit/s UDP load.

| Round | DU CSV rows | UL KPM/iperf | DL KPM/iperf |
| --- | ---: | ---: | ---: |
| 1 | 400 | 1.039124 | 1.029172 |
| 2 | 400 | 1.037342 | 1.031714 |
| 3 | 390 | 1.040306 | 1.030726 |

No duplicate exported DU records were found. The third run contains
39 report groups; this alone does not establish source-report loss.
An earlier retained single-UE run also passed 80 directional PRB
arithmetic checks, with inferred availability plus usage of 51 PRBs.
That arithmetic check is not independent scheduler accuracy validation.

PDCP acceptance requires at least five UL interior KPM reports with
median success at least 95 percent. KPM receipt timing requires at least
30 reports, median gap 0.8--1.2 seconds and maximum gap 1.5 seconds.

Aggregator trace checks require one UE/bearer, matched TX/RX counters,
consecutive batch counters, at least five positive RX batches during
the UL interior, median gap 0.8--1.2 seconds and maximum gap 1.5 seconds.

| Round | KPM reports | Maximum KPM gap (s) | Positive UL batches | Maximum UL batch gap (s) | Median success |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 40 | 1.007456 | 8 | 1.000186 | 100% |
| 2 | 40 | 1.013876 | 8 | 1.000239 | 100% |
| 3 | 40 | 1.004047 | 8 | 1.000060 | 100% |

All three PDCP runs had matched, consecutive batch counters.
Batch progression does not prove which cached batches contributed to
each individual KPM ratio.

## Clock changes and C++ tests

The initial CU-UP test established discovery, subscription and traffic,
but failed the minimum UL sample count. Reports slowed under traffic.
The existing independent KPM report-clock wiring covered the DU only.

`patch-ocudu-cu-up-kpm-wall-clock.py` extends the optional report clock
to CU-UP KPM scheduling while retaining protocol timer wiring.

`patch-ocudu-pdcp-metrics-clock.py` optionally selects an independent
statistics timer manager for PDCP TX/RX metrics. It retains the existing
protocol timer factories, counter reset calls and TX/RX matching rule.

Runtime options:

- `OCUDU_KPM_WALL_CLOCK=1`: enables the optional report-clock source.
- `OCUDU_PDCP_METRICS_WALL_CLOCK=1`: selects that source for PDCP statistics.
- `OCUDU_PDCP_METRICS_TRACE=1`: logs matched aggregator batch counters
  and RX packet counts for diagnostics.

The C++ test image ran the existing TX/RX metrics suites plus four new
isolation tests. The new tests check statistics reporting while protocol
timers are paused, TX discard/RX reordering isolation, period-counter
progression and metric clearing. Existing suites exercise the default
timer path.

```bash
sudo docker build -f docker/ocudu/Dockerfile.pdcp-metrics-clock-test --target test --build-arg BUILD_JOBS=1 -t limx59/oai-pi-ocudu-kpm-tests:arm64-pdcp-metrics-clock-test .
```

The runtime build is defined in
`docker/ocudu/Dockerfile.kpm-pdcp-metrics-clock`. Patches are applied inside
the build image; host upstream source trees remain unchanged.

## Optional Compose overlay

`deploy/ocudu/compose.pdcp-metrics-clock.yaml` pins the published gNB
digest, enables the clocks and trace, and mounts the CU-UP-only
`test/ocudu/config/gnb-zmq-pdcp.yml` configuration.

Apply it after the ZeroMQ, worker, E2 and collection-clock Compose files,
with `deploy/ocudu` as the Compose project directory. The configuration
points to the baseline RIC at `172.22.0.162`.

Its merged image, flags, CPU allocation and read-only configuration
mount passed configuration checks. Runtime validation used each
validator's generated override and temporary RIC; this standalone
overlay was not separately started. The validators remain the tested
acceptance entry points.

## Retained evidence and diagnostic scripts

Evidence under `~/Work/oai-test-evidence/`:

- `ocudu-radio-stats-2ko5z9h_`: initial DU statistics pass.
- `ocudu-pdcp-stats-j7yh6hou`: initial CU-UP insufficient-sample failure.
- `ocudu-pdcp-report-clock-pshm7ld3`: independent CU-UP report-clock pass.
- `ocudu-pdcp-metrics-clock-s2ev8ktw`: independent statistics-clock pass.
- `ocudu-statistics-regression-qcl83dbg`: all six regression runs,
  including links to individual evidence directories in `summary.json`.

`validate-pdcp-stats.py` and `validate-pdcp-report-clock.py` are retained
as independent diagnostic stages. The latter requires the published intermediate
report-clock image listed above.

## PDCP batch-history follow-up

The opt-in PDCP history and provenance stage passed nineteen C++ tests,
nine reviewer checks and three additional integration rounds on
2026-10-25, Pacific time. It adds per-UE/bearer history, receipt-age
filtering and calculation provenance with temporal/value CSV association.

See [PDCP batch history and provenance](README.pdcp-batch-history.md)
for behavior, published images, independent build/test commands,
evidence and limits. The standalone overlay has configuration-merge
validation; runtime acceptance uses the integration validator.

The remaining items below continue to describe the broader scope.
Temporal association and constructed-input tests do not establish
on-wire query identity or automatic lifecycle/reset recovery.

## Remaining work

- Correlate KPM output with identified source batches and detect stale
  cached input, rather than relying on changing export timestamps.
- Validate source-batch duplicate/missing handling and counter resets.
- Independently verify scheduler accuracy beyond single-UE arithmetic.
- Extend UE/bearer identity coverage beyond the single-UE setup.
- Validate PDCP reordering-delay delivery and any claimed delay/loss
  comparisons with appropriate independent evidence.
- Broaden xApp compatibility and sustained-session coverage.
