# MAC / RLC / PDCP statistics: original KPM demo main

## Status and scope

The original shared `test/xapp/xapp_kpm.py` passed the bounded OCUDU DU
normal subscription/report/delete flow. The actual original main and
callback ran directly, without monkey-patching or replacement.

CU-UP original-demo execution remains pending. Overall xApp compatibility
also remains incomplete; QoS and custom service models are outside this run.

## Reproduce

Follow the existing [compatibility prerequisites](README.xapp-compatibility.md).
Keep shared Open5GS and the baseline RIC running. Stop experimental gNB/UE,
run tests serially and let the validator manage container startup/cleanup.

From the repository root:

```bash
python3 -B test/ocudu/validate-xapp-demo-main-du.py
```

The test reuses the published ARM64 image:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-xapp-compatibility-test@sha256:bc6c6f46d8338bfab83d2ccbf7bd578028680d0c114cc99cd72b31646156d587
```

No image rebuild or new publication was needed. Required RIC/gNB/UE images
are listed in the validator constants and must already be local.

## Compose and original-code verification

`deploy/ocudu/compose.xapp-demo-main.yaml` overrides the container entrypoint
to run `/opt/ocudu-xapp-compatibility/xapp_kpm.py` directly with the generated
xApp configuration. It does not run the compatibility probe.

The validator creates the xApp through Compose and starts it with
`docker start -a`. Before execution it copies the packaged original script
to evidence and compares its bytes with the repository source.
The entrypoint, actual image ID, resolved Compose configuration and source
SHA-256 are retained.

The demo keeps its original two-second discovery wait and ten-second
recording period. An external 45-second timeout bounds a stuck process;
a timeout or nonzero exit fails acceptance.

## Checks and evidence

Evidence under `~/Work/oai-test-evidence/`:
`ocudu-xapp-demo-main-du-jb3ellka`.

| Check | Result |
| --- | --- |
| Original packaged script matches source | Yes |
| Reports | 10 |
| Numeric samples per throughput metric | 10 |
| UE report markers | 10 |
| Normal subscription deletion | Passed |
| Process exit and cleanup | Passed |
| Baseline RIC identity | Unchanged |

Original script SHA-256:
`dbd45b9e875dbeb33c5b28030db45703cb143e8c508666aa7a6c7161474dae5d`.

The log reviewer requires one subscription for node 420 and the configured
DU throughput metrics, at least five complete reports and three numeric
samples per metric, finite nonnegative values, expected UE report markers,
one deletion response and absence of callback/format/error markers.

A valid synthetic log and ten corrupted-output rejection checks passed.
Compose entrypoint, config path, Style 4 and pinned image checks passed.

## Boundaries

One DU/UE and one subscription only. This normal-flow test does not prove
negative-handle handling, empty-discovery behavior, automatic reconnection,
multi-node selection or sustained-session stability.

There is no UL/DL iperf comparison in this test. The retained framework
starts a traffic endpoint and performs readiness ping, but throughput
measurements may be zero and remain valid for parsing acceptance.

The original demo logs node ID and UE report index, not full component/UE
identity or indication-format metadata. Report structure checks are not
full protocol conformance. Prior DU/CU-UP recorder tests remain separate
evidence and do not substitute for original-demo execution.
