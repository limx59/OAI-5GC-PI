# MAC / RLC / PDCP statistics: xApp compatibility

## Status and scope

Completed subset: the unchanged shared KPM recorder reads OCUDU DU
Format 3 throughput reports in the dedicated xApp image, launched through
the dedicated Compose service and checked under uplink/downlink traffic.

The overall xApp compatibility item remains incomplete. The tested DU
advertises KPM only; custom MAC/RLC/PDCP unsupported boundaries were
audited without subscriptions. CU-UP capability auditing remains
pending. Recorder, original demo and shared QoS results remain separate.

The probe imports unchanged copies of `test/xapp/xapp_kpm.py` and
`test/xapp/xapp_kpm_recorder.py`. It supplies its own subscription lifecycle
and strict callback checks; this does not validate the original demo main.

## Prerequisites

Use the existing ARM64 OCUDU ZeroMQ/Open5GS environment and the
[radio statistics prerequisites](README.radio-stats.md).
Keep shared Open5GS and the baseline RIC running. Experimental gNB/UE must
be stopped. Run validators serially; do not start the probe Compose alone.

The validator requires local RIC, gNB and UE images referenced in its
constants. It does not build or automatically pull images. Its host
readiness check does not establish SBI health.

## Published xApp image

Remote digest and linux/arm64 manifest were verified after publication.

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-xapp-compatibility-test@sha256:bc6c6f46d8338bfab83d2ccbf7bd578028680d0c114cc99cd72b31646156d587
```

## Joint test

Run from the repository root:

```bash
python3 -B test/ocudu/validate-xapp-compatibility-compose-du.py
```

The validator starts an isolated RIC, experimental gNB/UE and traffic
endpoint. It resolves `deploy/ocudu/compose.xapp-compatibility.yaml`,
creates its xApp service with Compose and starts it using `docker start -a`.
The actual image ID and resolved configuration are retained in evidence.

Compose uses an external `docker_open5gs_default` network and requires
`OCUDU_COMPAT_EVIDENCE` pointing to an existing directory containing the
generated `xapp.conf`. The validator supplies these settings through a
private environment file and uses a unique project name.

The test checks DU/node/PLMN identity, Format 3, both throughput metrics,
finite nonnegative values, complete measurement pairs, at least 30 reports,
UL/DL application traffic and a KPM/iperf ratio of 0.70–1.50 with at least
five interior receipt-time samples per direction. Raw throughput is kbps;
only throughput values are multiplied by 1000 for comparison.

It checks one normal subscription deletion response and stable RAN/test
RIC identities. Temporary containers are removed; the original RAN
configuration is restored stopped and the baseline RIC is retained.

## Acceptance evidence

Directory under `~/Work/oai-test-evidence/`:
`ocudu-xapp-compatibility-compose-du-a67n3vk2`.

| Check | Result |
| --- | --- |
| Probe / CSV reports | 40 / 40 |
| CSV rows | 80 |
| Callback / cleanup errors | None |
| UL receiver | 993817 bit/s; zero reported packet loss |
| DL receiver | 1000148 bit/s; zero reported packet loss |
| UL KPM/iperf ratio | 1.032955; 9 samples |
| DL KPM/iperf ratio | 1.031816; 8 samples |
| Baseline RIC | Identity unchanged |

Earlier evidence `ocudu-xapp-compatibility-compose-du-lasm36yo` exposed
an unsynchronized summary snapshot (39 reports versus 40 CSV groups).
The new probe serializes callbacks and closes recording under the same
lock before taking the summary snapshot. An in-progress callback finishes;
callbacks arriving after that boundary are ignored. This is a bounded
recording policy, not proof that the SDK delivers no callbacks after delete.

The revised image passed the joint test above. Digest pinning followed
that run; a full post-pinning runtime rerun has not yet been performed.

## Limitations and remaining work

Single DU/UE and two throughput metrics only. Traffic association uses
receipt timestamps, not precise source windows or protocol query IDs.
The shared recorder schema does not retain CU/DU component ID or actual
UE identity. This run does not establish multi-component isolation,
source-batch freshness, protocol conformance or custom-SM compatibility.

Offline checks covered integer/real/no-value handling and rejection of
wrong node, role, format, metrics, NaN, negative values and malformed rows.
Mock SDK checks do not replace the live SDK/Compose test.

Remaining: CU-UP custom MAC/RLC/PDCP advertised-capability audit.
No custom-SM delivery has been validated. Original-demo failure paths,
reconnect and real QoS degradation/recovery remain outside scope.

## CU-UP shared-recorder extension

Style 1 / Format 1 passed with the same published image and a dedicated
Compose configuration: 40 reports, 19 complete numeric rows, 21 no-value
rows and UL median success of 100 percent. Cleanup succeeded and the
baseline RIC was retained. The DU evidence above remains a separate run.

See [CU-UP compatibility and reproduction](README.xapp-compatibility-cuup.md).

## Original shared KPM demo: DU normal flow

The unchanged original main and callback passed a separate Compose joint
test: ten reports, ten numeric samples per metric, normal deletion and
successful cleanup. The packaged script matched repository source bytes.
This does not extend the recorder evidence into original-demo throughput
comparison or failure recovery.

See [Original KPM demo main](README.xapp-demo-main.md).

## Original shared KPM demo: CU-UP normal flow

A separate original-demo CU-UP run passed: nine node-level reports,
eight numeric PDCP values, normal deletion and successful cleanup.
Packaged original script bytes matched source. The same published image
was reused; no new image publication was required.

See [Original KPM demo main](README.xapp-demo-main.md).

## Original shared QoS xApp compatibility

The unchanged shared QoS xApp passed four dedicated image/Compose joint
scenarios: uplink/downlink with forced alerts and no-alert controls.
Alerts occurred once per metric after two consecutive low observations;
zero-threshold controls produced no alerts. All runs had active traffic,
successful cleanup and unchanged baseline RIC.

The dedicated QoS image was published and its remote ARM64 digest verified.
This validates forced-threshold compatibility, not real QoS degradation
or recovery injection.

See [Shared QoS xApp compatibility](README.xapp-qos-compatibility.md).

## Custom MAC/RLC/PDCP capability boundary: DU

The independent SDK discovery probe and RIC acceptance logs agree that
the tested DU advertises only KPM ID 2. Custom IDs 142/143/144 are absent.
No subscriptions were sent and the original radio-stats main was not run.

This is a passed unsupported-boundary audit, not custom-model delivery
compatibility. The dedicated image was published and digest/platform
verified; cleanup succeeded and the baseline RIC was retained.

See [Custom service-model capability boundary](README.xapp-custom-sm-capability.md).
