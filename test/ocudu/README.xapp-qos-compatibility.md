# MAC / RLC / PDCP statistics: shared QoS xApp compatibility

## Status and scope

Passed for the original shared `xapp_qos_watch.py` against one OCUDU DU/UE:
uplink/downlink traffic, forced alerts and no-alert controls.

All three packaged shared modules were compared byte-for-byte with source:
`xapp_kpm.py`, `xapp_kpm_recorder.py`, and `xapp_qos_watch.py`.
Their code was not modified. The original QoS main supplies its own callback
to the original KPM demo as implemented in the existing shared code.

This is an xApp compatibility subset, distinct from the earlier OCUDU
specific QoS monitoring case. Overall xApp compatibility remains open.

## Prerequisites and published image

Follow [compatibility prerequisites](README.xapp-compatibility.md).
Keep shared Open5GS and the baseline RIC running. Experimental gNB/UE must
be stopped; run scenarios serially. The validator manages test containers.

The dedicated ARM64 image was published and its remote digest/platform
verified after all four scenarios passed:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-xapp-qos-compatibility-test@sha256:d7292a9ec58460120ad22b82d98f533161e7ad48a689e240b431352385d644d0
```

Required RIC/gNB/UE images are listed in the validator constants.
No automatic build or image pull occurs during validation.

## Reproduce

Run separately from the repository root; stop on the first failure:

```bash
python3 -B test/ocudu/validate-xapp-qos-compatibility.py --direction uplink --case alerts
python3 -B test/ocudu/validate-xapp-qos-compatibility.py --direction uplink --case no-alerts
python3 -B test/ocudu/validate-xapp-qos-compatibility.py --direction downlink --case alerts
python3 -B test/ocudu/validate-xapp-qos-compatibility.py --direction downlink --case no-alerts
```

The validator creates the xApp using
`deploy/ocudu/compose.xapp-qos-compatibility.yaml`, then starts it with
`docker start -a`. Resolved Compose configuration, actual image ID,
original module hashes, stdout/stderr and iperf results are retained.

Compose requires an explicit `OCUDU_QOS_THRESHOLD`; the validator supplies
it through its generated environment file. Consecutive low reports is 2.
The original ten-second QoS/demo observation period remains unchanged,
bounded externally by a 45-second process timeout.

## Acceptance semantics

The high threshold is 1e9 in raw agent-reported kbps, deliberately forcing
both throughput metrics below threshold. Each metric must alert exactly
once immediately after its second low observation. Threshold zero is the
no-alert control; nonnegative measurements must not trigger an alert.

At least five observations per metric and two later positive observations
for the active direction are required. Each single-UE observation must
have one valid sample. Callback errors, malformed reports, unexpected
recovery/unknown events and missing/repeated alerts fail acceptance.

Each scenario also runs 15 seconds of 1 Mbit/s UDP traffic. Receiver rate
must be at least 800 kbit/s with loss at most 5 percent. These checks
establish active business traffic; they do not compare QoS means directly
with iperf or validate real congestion.

The validator checks normal subscription deletion, successful exit,
stable RAN/test RIC identity, cleanup and unchanged baseline RIC.
Original RAN configuration is restored stopped.

## Retained acceptance evidence

Directories are under `~/Work/oai-test-evidence/`.
Observation and alert columns are DL/UL metric counts.

| Scenario | Observations DL/UL | Alerts DL/UL | Evidence |
| --- | --- | --- | --- |
| uplink / alerts | 9/9 | 1/1 | `ocudu-xapp-qos-uplink-alerts-vzp4w0c3` |
| uplink / no-alerts | 10/10 | 0/0 | `ocudu-xapp-qos-uplink-no-alerts-jp_tptn7` |
| downlink / alerts | 10/10 | 1/1 | `ocudu-xapp-qos-downlink-alerts-qymiqynh` |
| downlink / no-alerts | 9/9 | 0/0 | `ocudu-xapp-qos-downlink-no-alerts-tzm9exqg` |

All four scenarios had zero reported application packet loss, no cleanup
errors, matching original modules and unchanged baseline RIC.
Four synthetic valid cases and eleven corrupted-output rejection checks
passed. Both Compose threshold configurations passed checks.

The image was pinned after these live runs; final pinning itself does not
constitute another runtime regression.

## Limitations and remaining work

Single DU/UE; two throughput metrics; forced-threshold behavior only.
Real QoS degradation, recovery injection, reconnect, multi-node/component
state isolation, PDCP QoS and long-term stability are not established.

No shared code was changed; the dedicated image only packages the original
QoS script on the previously published compatibility image.
Custom MAC/RLC/PDCP service-model compatibility remains pending.
