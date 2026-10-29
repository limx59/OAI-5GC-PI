# Traffic steering policy: single-link load response

## Status and scope

Passed for one OCUDU DU and one OAI ZeroMQ UE. The dedicated image,
Compose service and independent validator were exercised together.
The packaged statistics collector matched the existing repository source.

This case validates load response before steering-policy integration.
It does not generate migration recommendations or send E2 control.
Sequential OAI/OCUDU comparison, dual-node recommendations and common
metrics/cooldown validation remain separate work.

## Prerequisites

Follow the [OCUDU integration prerequisites](README.md#prerequisites).
Keep shared Open5GS and the baseline RIC running. Experimental gNB/UE
must be stopped. Run tests serially; no manual container startup is needed.

The validator requires all referenced images locally. It does not build
or automatically pull images. Pull the published test image first:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-steering-load-response-test@sha256:bbd96295b93df54c58ca38d438e5aa84dcbfa9859f9c4fc093f5dbc2a10bae5a
```

## Reproduce

Run from the repository root:

```bash
python3 -B test/ocudu/validate-steering-load-response.py
```

The validator creates an isolated temporary RIC, starts the experimental
RAN, traffic endpoint and Compose collector, and runs these phases serially:

| Direction | Phase | Offered UDP rate | Duration |
| --- | --- | --- | --- |
| Uplink | low-before | 200 kbit/s | 10 seconds |
| Uplink | high | 1 Mbit/s | 10 seconds |
| Uplink | low-after | 200 kbit/s | 10 seconds |
| Downlink | low-before | 200 kbit/s | 10 seconds |
| Downlink | high | 1 Mbit/s | 10 seconds |
| Downlink | low-after | 200 kbit/s | 10 seconds |

The collector records ten scheduler/RLC metrics for 110 seconds.
The dedicated Compose file is
`deploy/ocudu/compose.steering-load-response.yaml`.

## Acceptance checks

- At least five interior nominal one-second KPM windows per phase.
- Receiver rate between 80 and 120 percent of offered rate; loss at most 5 percent.
- Median KPM throughput / receiver rate between 0.70 and 1.50.
- High-phase KPM throughput at least three times either low phase.
- Final/initial low-phase throughput ratio between 0.70 and 1.30.
- Complete ten-metric groups, stable UE/component identity and valid units.
- Normal subscription deletion, unchanged running RAN/RIC identities during
  measurement and successful cleanup.

Window association uses the KPM header plus row granularity. These are
nominal windows, not independently identified source measurement batches.

## Retained acceptance evidence

Directory: `~/Work/oai-test-evidence/ocudu-steering-load-response-myxaa3c8/`.

The passing run recorded 110 reports and 1100 CSV rows, with no callback
or cleanup errors. All six traffic phases had zero receiver packet loss.

| Phase | Interior reports | Median KPM kbit/s | KPM/iperf | Median PRB utilization % |
| --- | --- | --- | --- | --- |
| uplink-low-before | 6 | 208.172 | 1.0405 | 0.0 |
| uplink-high | 7 | 1026.832 | 1.0315 | 3.0 |
| uplink-low-after | 6 | 208.348 | 1.0436 | 0.0 |
| downlink-low-before | 7 | 208.192 | 1.0377 | 3.0 |
| downlink-high | 6 | 1035.084 | 1.0338 | 29.0 |
| downlink-low-after | 7 | 207.432 | 1.0339 | 1.0 |

## Interpretation and cleanup

PRB utilization is an integer scheduler statistic. Zero at low load may
reflect quantization; it does not establish zero resource consumption.
This bounded test does not establish scheduler capacity or saturation.

The existing two-cell FlexRIC steering baseline uses controlled emulator
loads. It must not be treated as an actual OAI radio-load comparison.

The baseline RIC was retained. Test containers were removed and the original
RAN configuration was restored, stopped. Evidence remains on the host.

The existing collector, shared xApps and previous validators were unchanged.
