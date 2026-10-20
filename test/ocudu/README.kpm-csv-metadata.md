# KPM CSV recording: metadata and UE identity validation

## Purpose

Validate DU KPM CSV metadata, nominal protocol windows, throughput units,
bounded UL/DL comparison and single-UE identity correlation.

Keep the two test scripts separate:

- `validate-kpm-csv-metadata.py`: baseline metadata and UL/DL comparison.
- `validate-kpm-csv-ue-identity.py`: the same checks plus independent
  correlation with gNB F1 context and UE creation logs.

The baseline script is retained independently from the identity test.

## Prerequisites

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Follow [the E2/KPM prerequisites](README.kpm-delete-rejection.md)
for the existing Open5GS deployment, private UE configuration and
`docker_open5gs_default` network.

Keep the shared core and baseline RIC at `172.22.0.162` running.
The experimental gNB and UE must be stopped before building or testing.
Do not run concurrent xApps or another experiment using the same RAN.
The temporary test RIC uses `172.22.0.163`; the traffic endpoint uses
`172.22.0.151`. Both addresses must be available.

Required existing images:

```text
limx59/oai-pi-ocudu-gnb:arm64-kpm-collection-clock
limx59/oai-pi-oai-nr-ue:arm64-zmq-test
```

The validator also requires the existing OCUDU Compose files and
collection-clock configuration used by the repository.
Run the scripts from their repository paths: their location determines
the repository root.

## Build the metadata images

Build on ARM64 with the experimental RAN stopped:

```bash
sudo docker build \
  -f docker/ocudu/Dockerfile.flexric-kpm-csv-metadata \
  --target xapp --build-arg BUILD_JOBS=2 \
  -t limx59/oai-pi-ocudu-flexric-xapp:arm64-kpm-csv-metadata-test .
```

```bash
sudo docker build \
  -f docker/ocudu/Dockerfile.flexric-kpm-csv-metadata \
  --target ric --build-arg BUILD_JOBS=2 \
  -t limx59/oai-pi-ocudu-flexric-ric:arm64-kpm-csv-metadata-test .
```

Both components require the KPM V3 header byte-order fix.
The xApp also includes optional scalar copying and numeric granularity
bindings. Building an image alone does not validate its runtime behavior.

## Pull published metadata images

Both ARM64 tags were pushed and pulled successfully on 2026-10-20,
Pacific time. Their published digests matched the tested images.
Use these images to skip the local metadata image builds.

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-kpm-csv-metadata-test
sudo docker pull limx59/oai-pi-ocudu-flexric-ric:arm64-kpm-csv-metadata-test
```

The existing gNB and UE images listed under Prerequisites are also required.

## Run the baseline test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  test/ocudu/validate-kpm-csv-metadata.py </dev/null
```

The validator recreates the experimental RAN, waits for the UE tunnel,
starts CSV recording and runs sequential UL/DL UDP traffic.
Each direction targets 1 Mbit/s for 10 seconds with 1200-byte datagrams.

## Run the independent UE identity test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  test/ocudu/validate-kpm-csv-ue-identity.py </dev/null
```

This test additionally correlates the CSV gNB-CU UE F1AP identifier with
the independently logged F1 context and the local UE's C-RNTI.
It requires one unambiguous UE context; it does not establish multi-UE
identity discrimination.

## Checks and acceptance criteria

- Node 420, DU 0 and the configured PLMN identity.
- One stable CU UE F1AP identifier within the run.
- Valid collection timestamps and 1000 ms granularity.
- Nominal row windows derived from the header and row granularity.
- Finite, nonnegative DL/UL values; kbps converted to bit/s by multiplying
  by 1000.
- Application receiver rate at least 800000 bit/s and loss at most 5%.
- At least five selected reports per direction.
- Median KPM rate / application receiver rate between 0.70 and 1.50.
- Normal subscription deletion and successful cleanup.
- Independent F1 context correlation in the identity test.

The comparison uses nominal interior windows against the whole-run
application receiver rate. These are experiment criteria, not protocol
conformance or calibrated measurement-accuracy guarantees.
Nominal windows are not exact RLC sample boundaries.

## Validated results

Validated on Raspberry Pi ARM64 across 2026-10-19 and 2026-10-20,
Pacific time, using the same four recorded image digests.

| Run | Reports / CSV rows | UL ratio | DL ratio | Result |
| --- | --- | --- | --- | --- |
| Initial baseline `ok8l819p` | 40 / 80 | 1.0302 | 1.0307 | Passed |
| Baseline retest `9v3hq1n6` | 39 / 78 | 1.0365 | 1.0309 | Passed |
| Identity test `mgy85ort` | 40 / 80 | 1.0394 | 1.0296 | Passed |

The latest baseline received approximately 0.994 Mbit/s UL and
1.000 Mbit/s DL. The identity test received approximately 0.994 Mbit/s
UL and 1.001 Mbit/s DL. Both runs had zero packet loss.

The identity test matched CSV CU-F1AP ID 0 to gNB logs showing
local UE 0, DU-F1AP ID 0, CU-F1AP ID 0 and C-RNTI `0x4601`.
Callback and cleanup errors were empty.
Report counts can differ at recording boundaries; CSV metric rows
must not be counted as separate indication reports.

## Evidence and cleanup

Evidence is retained outside Git under:

```text
~/Work/oai-test-evidence/ocudu-kpm-csv-metadata-ok8l819p
~/Work/oai-test-evidence/ocudu-kpm-csv-metadata-9v3hq1n6
~/Work/oai-test-evidence/ocudu-kpm-csv-ue-identity-mgy85ort
```

Inspect the summary, `kpm.csv`, probe output, traffic results and
gNB identity logs. The identity validator includes its correlation
result in the summary.

The validators remove temporary test services, restore the original
RAN configuration and leave the experimental RAN stopped.
The successful runs retained the baseline RIC container identity,
PID, start time and restart count.
Review cleanup errors before starting another test.

## Registration failure encountered during retesting

Some retests failed before the UE tunnel was ready. Correlated logs
showed HTTP 400 propagation through UDM, AUSF and AMF, Registration
Reject 95, and SCP reporting `No NF-Instance [nudr-dr:UDM]`.

Direct NRF discovery returned the registered UDR service. Earlier logs
also recorded NF heartbeat loss and re-registration.
The configuration was unchanged across the successful and failed runs.

Restarting AUSF did not restore the test. Restarting SCP afterward also
did not restore it. After UDM was subsequently restarted, the baseline
and independent identity tests passed.

This records an observed recovery sequence, not a proven root cause
or proof that restarting UDM alone is sufficient.
Do not automatically restart shared core services as a test prerequisite.

Compare successful and failed requests in matching time windows.
Endpoint `:80`, `type:NULL`, `already been added`, `validity:0s`, or
empty NRF/UDR logs alone are not failure evidence: they also appeared
in the successful run or its log window.
Incomplete diagnostic paths can themselves return HTTP 400/500;
they must not be treated as authentication test results.

## Source patch archive

[Metadata patch snapshots](patches/kpm-csv-metadata/README.md) retain
four original and patched source files, a unified diff and SHA-256
checksums. The manifest records the three metadata patches in order.

This archive covers the metadata transformations only. Earlier
interoperability patches are applied separately by the Dockerfile.
The snapshot replay does not replace compilation or runtime validation.
