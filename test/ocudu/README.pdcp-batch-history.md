# PDCP batch history and provenance

## Validated scope

Validated on the ARM64 Raspberry Pi on 2026-10-25, Pacific time.

- Ten C++ batch-history tests and nine provider behavior tests passed.
- Nine retained-evidence reviewer tests passed, including corrupted inputs.
- Three serial PDCP integration runs passed with calculation provenance
  and unique temporal/value CSV association required for acceptance.
- Three new images were pushed and pulled with the expected digests.

This extends [the statistics validation](README.radio-stats.md).
The complete MAC / RLC / PDCP statistics test case remains partially
complete. This stage does not validate live source fault injection,
automatic source-lifecycle detection, reset recovery, protocol query-ID
transport, PDCP reordering delay or physical RF.

## Provider behavior

`OCUDU_PDCP_BATCH_HISTORY=1` enables the experimental success-rate path.
Without it, the existing provider path remains selected.

History is isolated by UE, bearer type and bearer ID. Each source retains
at most ten accepted batches. A globally increasing local revision
identifies each accepted input within the provider instance.

The implementation:

- Rejects duplicate counters without refreshing receipt age.
- Rejects mismatched TX/RX counters.
- Records forward gaps without fabricating missing samples.
- Rejects ambiguous backward/half-range counter discontinuities.
- Accepts ordinary unsigned counter wrap.
- Excludes batches aged 2500 ms or more from a calculation.
- Returns `no_value` when no eligible batch or no RX PDU denominator exists.
- Exposes an explicit epoch operation for an independently established
  lifecycle boundary; runtime lifecycle detection is not connected.

Receipt age uses `steady_clock` inside the provider. It does not measure
time spent before provider ingress and is not an exact source collection
boundary. The 2500 ms limit is an experimental choice, not a protocol SLA.

A counter decrease alone cannot distinguish reset from delayed/old data.
Unit tests exercise an explicit epoch transition; they do not prove
automatic runtime reset detection or rejection of all late old-epoch input.

Fresh batches may participate in adjacent calculations. This is a rolling
history, not a consume-once or non-overlapping measurement window.

The new age-based success-rate calculation does not establish equivalent
freshness behavior for other CU metrics such as PDCP reordering delay.

## Diagnostic records and review

- `PDCP_BATCH_INPUT`: admission status, UE/bearer, counters, revision,
  epoch and RX counts.
- `PDCP_KPM_SOURCE`: revisions and counts used by one local query.
- `PDCP_KPM_RESULT`: selected/expired counts, sums and resulting value.

`review-pdcp-provenance.py` verifies accepted revision references,
payloads, unique batches within a calculation, age bounds, capacity
selection, sums, float32 percentage arithmetic and CSV values.

Application timestamps lack an explicit timezone suffix. The reviewer
interprets them as UTC and checks each against Docker's timestamp within
five seconds. Receipt-age crosschecks allow 50 ms logging tolerance and
reject ambiguous age-boundary evidence.

CSV/query association requires one candidate within 100 ms of the nominal
window end and a receipt offset between -10 and 500 ms, plus an exact
value/type match. This was validated for a single subscription.
No provider query ID is transported in the standard KPM report.

The first review failed because the original parser required a timezone
on the application timestamp. The parser was corrected and the failed
result retained. No container rerun was required.

## Build and test are separate

Build the provider unit-test image with two compiler processes:

```bash
sudo docker build -f docker/ocudu/Dockerfile.pdcp-provider-batch-test --target test --build-arg BUILD_JOBS=2 -t limx59/oai-pi-ocudu-kpm-tests:arm64-pdcp-provider-batch-test .
```

Run the nineteen C++ tests separately:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/validate-pdcp-provider-batch-unit.py </dev/null
```

The unit runner uses an isolated container with `--network none`, checks
the exact two suites and nineteen tests, retains logs/JUnit XML/summary
and removes the temporary container. Inputs are constructed C++ metrics.

The component-only history image was initially built with ten tests
executed during that build. After the user requested separation, both
new unit-test Dockerfiles were changed to compile only. The provider
image was subsequently built and its nineteen tests run separately.

Build the runtime gNB image independently:

```bash
sudo docker build -f docker/ocudu/Dockerfile.kpm-pdcp-batch-history --target gnb --build-arg BUILD_JOBS=2 -t limx59/oai-pi-ocudu-gnb:arm64-kpm-pdcp-batch-history-test .
```

The observed runtime build took about 2626 seconds. This is not a
controlled compiler-speed comparison with earlier builds.

## Integration prerequisites and commands

Follow [the statistics prerequisites](README.radio-stats.md).
Keep shared Open5GS and the baseline RIC running. The experimental gNB/UE
must be stopped before testing. No concurrent experiments are allowed.

The validator uses the existing Compose files to recreate experimental
gNB/UE, a temporary RIC at `172.22.0.163`, an xApp and traffic endpoint
at `172.22.0.151`. It checks UL/DL traffic, clocks, provenance and cleanup,
then restores the original RAN configuration stopped.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/validate-pdcp-batch-history.py </dev/null
```

Three serial runs, stopping at the first failure:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/validate-pdcp-batch-regression.py --rounds 3 </dev/null
```

The regression records source hashes and individual evidence paths.
No image build is performed by these test scripts.

## Results and retained evidence

All evidence paths below are under `~/Work/oai-test-evidence/`.

| Evidence | Result |
| --- | --- |
| `ocudu-pdcp-provider-batch-unit-xkcafotf` | 19 tests; zero failures, disabled, skipped or errors; cleanup successful |
| `ocudu-pdcp-batch-history-zkyy23y6` | Initial integration and retained-log review |
| `ocudu-pdcp-batch-regression-3q1nzawr` | Three integration/provenance runs passed |

Regression child directories:

| Round | Evidence |
| --- | --- |
| 1 | `ocudu-pdcp-batch-history-ijjoh_nn` |
| 2 | `ocudu-pdcp-batch-history-1u6c7au5` |
| 3 | `ocudu-pdcp-batch-history-p9rfiu8k` |

The initial retained review checked 60 accepted inputs, 40 calculations,
80 source references and 40 CSV rows. All 21 unavailable values had a
zero denominator. Thirty-nine revisions were reused across queries.
The cumulative excluded expired-entry count was 320; it does not mean
320 distinct source batches.

The validator's first capture had 59 inputs; its final diagnostic capture
included one additional input before cleanup. Review results above refer
to the final retained log. This does not indicate a missing KPM report.

The three regression runs required the integrated reviewer to pass.
The baseline RIC was retained and cleanup passed. Short repeated tests
do not establish sustained-session or long-term stability.

Replay the initial evidence without containers:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/test-pdcp-provenance.py ~/Work/oai-test-evidence/ocudu-pdcp-batch-history-zkyy23y6 </dev/null
```

The standalone reviewer refuses to overwrite an existing output.
Use `--output` for a new review filename:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B test/ocudu/review-pdcp-provenance.py ~/Work/oai-test-evidence/ocudu-pdcp-batch-history-zkyy23y6 --output /tmp/pdcp-provenance-review-new.json </dev/null
```

## Published images

All three tags were pushed and pulled successfully on 2026-10-25,
Pacific time:

```bash
sudo docker pull limx59/oai-pi-ocudu-gnb:arm64-kpm-pdcp-batch-history-test@sha256:c4d6f51770b6adc9e5bcec42b9fdc6986717e4426d5595f3d63788bab76a7377
sudo docker pull limx59/oai-pi-ocudu-kpm-tests:arm64-pdcp-provider-batch-test@sha256:7755aa187e66be48b72bc11cf88507f655ca10bc29c3f5ce09008042bbfcaee6
sudo docker pull limx59/oai-pi-ocudu-kpm-tests:arm64-pdcp-batch-history-test@sha256:8c5c4c0dd9a907060da7f0e0109901990a4071f73587aa999f72fdd13649d042
```

The runtime image matches the integration image; the provider-test image
matches the nineteen-test evidence. Tests use local images with pulling
disabled; the successful pulls establish that these tags are published,
not that every run downloads them anew.

## Optional Compose overlay

`deploy/ocudu/compose.pdcp-batch-history.yaml` fixes the published runtime
digest and enables the report clock, statistics clock, trace and history.

Apply it last after ZeroMQ, worker, E2 and collection-clock files.
Merged image, flags, CPU allocation and read-only configuration mount
passed configuration checks.

The standalone overlay points to the baseline RIC at `172.22.0.162`
and was not separately started. The integration validators use generated
overrides and a temporary RIC. Do not claim these are the same runtime
validation.

## Remaining acceptance work

- Actual source fault injection and recovery rather than only constructed
  C++ input and mutated-log rejection.
- Independently established producer lifecycle epochs and reset recovery.
- Stronger on-wire report/source identification beyond temporal matching.
- Broader MAC/RLC source freshness and independent scheduler accuracy.
- PDCP reordering-delay delivery, multiple real UEs/bearers and broader
  xApp compatibility.

Unit-level UE/bearer isolation does not establish multi-UE network
integration. Existing successful scripts, images and configurations remain
independent baselines.
