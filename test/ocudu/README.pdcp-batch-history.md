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
complete. The initial stage did not validate live faults or reset recovery.
The controlled extension now covers these for one UE/bearer.
Protocol query-ID transport, PDCP reordering delay and physical RF
remain outside the validated scope.

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
  lifecycle boundary. The source-instance extension connects aggregator
  replacement to an epoch transition.

Receipt age uses `steady_clock` inside the provider. It does not measure
time spent before provider ingress and is not an exact source collection
boundary. The 2500 ms limit is an experimental choice, not a protocol SLA.

A counter decrease alone cannot distinguish reset from delayed/old data.
Live tests cover source reconstruction and one controlled old-source
replay. They do not establish recovery across provider/process restarts
or rejection of every possible delayed-input pattern.

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

- Broader fault patterns, concurrent sources and provider/process restarts
  beyond the controlled single-UE source-replacement experiment.
- Stronger on-wire report/source identification beyond temporal matching.
- Broader MAC/RLC source freshness and independent scheduler accuracy.
- PDCP reordering-delay delivery, multiple real UEs/bearers and broader
  xApp compatibility.

Unit-level UE/bearer isolation does not establish multi-UE network
integration. Existing successful scripts, images and configurations remain
independent baselines.

## PCI and RNTI selection for lifecycle tests

PCI is read dynamically from the generated test gNB configuration.
Adapt `test/ocudu/config/gnb-zmq-pdcp.yml` to the local cell configuration
when necessary. No PCI or RNTI edits in the Python validators are required.

RNTI is derived from successful MAC UE creation and removal records.
Removed contexts are excluded. Discovery requires one configured PCI and
exactly one active MAC UE context; ambiguity stops the test. Do not hardcode
a previous RNTI or select the last observed value. Multiple-cell or multiple-UE
environments require an explicitly validated target-selection extension.
Fixed identifiers in synthetic fixtures are test data, not runtime targets.

## Controlled source-lifecycle validation — 2026-10-27

The `validate-pdcp-source-lifecycle-late-source.py` run passed:
source instance 2 -> 5, counter 56 -> 0, epoch 1 -> 2.
One real positive-RX old-source report was replayed during KPM recording
and rejected with status 7. New-source continuity and 37 subsequent
calculations were checked. All 80 pre/post KPM CSV associations passed.
Post-reconstruction uplink/downlink traffic had zero reported packet loss.
Component identities remained unchanged; cleanup reported no errors and
the baseline RIC was retained.

Evidence directory: `ocudu-pdcp-source-lifecycle-late-source-x2uyy2w4`
under `~/Work/oai-test-evidence/`.

Scope: single UE/bearer, controlled statistics-report injection and
sequential pre/post subscriptions. CSV correlation uses timestamps and
values; no protocol query ID is exported. This does not establish physical
RF performance, multi-UE coverage or long-term stability.

## Reproduce duplicate, missing and reset detection

The controlled case passed within the single-UE/bearer statistics-delivery
scope. Broader xApp compatibility remains pending.

Run from the repository root after following the statistics prerequisites.
Keep shared Open5GS and the baseline RIC running. Experimental gNB/UE must
be stopped; run tests serially. Validators manage their own test containers
and restore the original RAN configuration stopped. Core-network restarts
are troubleshooting actions, not routine test setup.

The final validators pin the published image digests. Pull the required
images using the commands in the following section before running tests.
Validators do not build or automatically pull images.

Run each command separately and stop on failure:

```bash
python3 -B test/ocudu/validate-pdcp-source-instance-unit.py
python3 -B test/ocudu/validate-pdcp-delivery-fault-clock.py --fault duplicate
python3 -B test/ocudu/validate-pdcp-delivery-fault-clock.py --fault drop
python3 -B test/ocudu/validate-pdcp-source-lifecycle-late-source.py
```

The lifecycle validator arms replay after three post-reset KPM reports.
Review checks the real old payload, status 7 rejection, new-source
counter/revision/epoch continuity and subsequent KPM calculations.
Faults affect metrics delivery, not PDCP traffic packets.

### Compose configuration

Optional overlays:

- `deploy/ocudu/compose.pdcp-delivery-fault.yaml`
- `deploy/ocudu/compose.pdcp-source-lifecycle.yaml`

Apply an overlay after the ZeroMQ, worker, E2 and collection-clock files.
The delivery overlay requires `OCUDU_PDCP_TEST_DELIVERY_FAULT` to be
`duplicate` or `drop`. With sudo, pass it using
`sudo env OCUDU_PDCP_TEST_DELIVERY_FAULT=duplicate docker compose ...`.

Duplicate, drop and lifecycle merged configurations passed configuration
validation. Standalone overlays were not separately started. Automatic
validators use generated overrides and a temporary RIC instead; these
are distinct validation scopes. Use the lifecycle validator to coordinate
release, reconstruction, KPM recording and replay arming.

## Published images for duplicate, missing and reset detection

These images were pushed and their remote digests and linux/arm64
manifests verified. Earlier source-instance and delivery-fault runtime
tags remain published stage versions.

```bash
sudo docker pull limx59/oai-pi-ocudu-kpm-tests:arm64-pdcp-source-instance-test@sha256:86fd51131dee1645c5e6a2671a8c51eccbbc4d7c2bc91aa59d138f5ce3caa46f
sudo docker pull limx59/oai-pi-ocudu-gnb:arm64-kpm-pdcp-provenance-clock-test@sha256:99a169ba550db2995c41d5ba401b3ef1d2ca820b83f7a481caf96a2efdffd620
sudo docker pull limx59/oai-pi-ocudu-gnb:arm64-kpm-pdcp-late-source-test@sha256:2977f56f56be6d6e9c9a69bd588d2d8902bff4c6f99a533d0dccab99b48b0b8c
```

### Retained acceptance evidence

Directories are under `~/Work/oai-test-evidence/`.

| Evidence | Verified result |
| --- | --- |
| `ocudu-pdcp-source-instance-unit-ac9pdohc` | 27 C++ tests passed |
| `ocudu-pdcp-delivery-clock-duplicate-mcvpydjk` | 12 duplicate reports rejected; 40 calculation/CSV checks passed |
| `ocudu-pdcp-delivery-clock-drop-4niujjml` | Six dropped reports and six detected gaps; 40 calculation/CSV checks passed |
| `ocudu-pdcp-source-lifecycle-late-source-x2uyy2w4` | Source reconstruction; one stale-source rejection; 80 calculation/CSV checks passed |

The passing lifecycle run checked 37 calculations after replay.
Cleanup succeeded and the baseline RIC was retained. These bounded
tests do not establish multi-UE coverage or long-term stability.
