# MAC / RLC / PDCP statistics: CU-UP xApp compatibility

## Status and scope

Passed for one CU-UP/UE using the unchanged shared KPM recorder,
Style 1 and indication Format 1. The dedicated CU-UP Compose service
configuration and independent validator were exercised together.

The probe supplies its own subscription lifecycle. The original shared
KPM demo main, QoS behavior and custom MAC/RLC/PDCP service models remain
outside this acceptance. Overall xApp compatibility remains incomplete.

## Prerequisites and image

Follow the [shared-recorder prerequisites](README.xapp-compatibility.md).
Keep shared Open5GS and the baseline RIC running; experimental gNB/UE
must be stopped. Run tests serially. No manual container startup is needed.

Reuse the already published and digest-verified ARM64 xApp image:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-xapp-compatibility-test@sha256:bc6c6f46d8338bfab83d2ccbf7bd578028680d0c114cc99cd72b31646156d587
```

The validator also requires the existing RIC and UE images and the pinned
PDCP provenance-clock gNB image listed in its constants. It does not build
or automatically pull images. No new xApp binary or image was needed.

## Reproduce

From the repository root:

```bash
python3 -B test/ocudu/validate-xapp-compatibility-compose-cuup.py
```

The validator generates isolated RIC, gNB and xApp configurations, enables
CU-UP E2 only, selects Style 1 and subscribes to
`DRB.PacketSuccessRateUlgNBUu`.

It enables the existing report/statistics clocks and PDCP batch history;
delivery-fault and late-source injection are disabled. This is not another
source-provenance or fault-injection validation.

The xApp is created through
`deploy/ocudu/compose.xapp-compatibility-cuup.yaml`, then started with
`docker start -a`. The resolved Compose configuration and actual image ID
are retained in the evidence directory.

The validator manages temporary RIC, RAN, traffic endpoint and xApp
containers. Cleanup restores the original RAN configuration stopped and
checks that the baseline RIC is unchanged.

## Acceptance

The reviewer requires at least 30 reports, node/PLMN identity, Format 1,
one node-level metric per report, empty no-value cells, finite numeric
percentages within 0..100, and matching probe/CSV counters.

UL receipt-time interior requires at least five complete numeric reports
with median success at least 95 percent. UL/DL application traffic is
checked separately; PDCP success is not application packet-loss rate.

## Retained evidence

Directory under `~/Work/oai-test-evidence/`:
`ocudu-xapp-compatibility-compose-cuup-agnj7jps`.

| Check | Result |
| --- | --- |
| Probe / CSV reports | 40 / 40 |
| CSV rows | 40 |
| Complete numeric / no-value rows | 19 / 21 |
| UL interior reports | 8 |
| UL median success | 100 percent |
| UL receiver | 992483 bit/s; zero reported packet loss |
| DL receiver | 1000289 bit/s; zero reported packet loss |
| Callback / cleanup errors | None |
| Baseline RIC | Identity unchanged |

The live run used pinned xApp and gNB image references. Nine offline
corrupted-evidence rejection checks and numeric/no-value fixtures passed.
Compose role, Style 1 and pinned image checks passed before live execution.

## Boundaries

Single CU-UP/UE only. CSV association uses receipt timestamps and cached
PDCP history, not precise source windows or an on-wire query ID.
The shared schema does not export component identity. This run does not
validate source provenance, multi-component isolation, reordering delay,
application-loss equivalence or sustained-session stability.

Recording closes under the probe's callback lock after the SDK shutdown
wait. An in-progress callback finishes before the snapshot; later callbacks
are ignored. This does not prove absence of callbacks after deletion.

The DU validator, shared recorder and published image remain unchanged.
