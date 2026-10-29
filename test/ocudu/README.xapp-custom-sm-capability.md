# MAC / RLC / PDCP statistics: custom-SM capability boundary

## Status and interpretation

The DU advertised-capability audit passed. The laboratory DU advertised
only KPM RAN Function ID 2, revision 0; the isolated RIC accepted ID 2.
Custom MAC/RLC/PDCP IDs were not advertised.

This is a verified unsupported boundary, not successful custom-SM
subscription or data delivery. CU-UP subsequently passed the separate
capability audit below with the same unsupported result.

| Model | FlexRIC custom ID | Advertised by tested DU |
| --- | --- | --- |
| MAC | 142 | No |
| RLC | 143 | No |
| PDCP | 144 | No |
| KPM | 2 | Yes |

These IDs are established by this FlexRIC source revision, not universal
protocol identifiers for every implementation.

## Source and runtime evidence

The SDK Python node exposes `node.ran_func`; each function has `id` and
`rev`. The probe reads this advertised list, not the local plugin list.
The RIC acceptance log supplies a separate cross-check.

The original `test/xapp/xapp_radio_stats.py` subscribes to configured
custom models without checking advertised per-node capabilities.
It was not executed or modified. Its custom MAC/RLC/PDCP interfaces are
not interchangeable with OCUDU KPM measurements.

The independent probe does not call subscription APIs. Unsupported models
are recorded as `unsupported_not_advertised`. Even an advertised custom
ID is classified as requiring a separate delivery test.

## Prerequisites and image

Follow [compatibility prerequisites](README.xapp-compatibility.md).
Keep shared Open5GS and the baseline RIC running. Experimental gNB/UE must
be stopped. Run serially; let the validator manage test containers.

The dedicated image was published and remote digest/linux-arm64 verified:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-custom-sm-capability-test@sha256:2c3add43804b9494a9d84037980c8dc2d48285214559d277e1d38ec4a6ee2e03
```

RIC/gNB/UE images in the validator constants must also be local.
Validation does not build or automatically pull images.

## Reproduce

From the repository root:

```bash
python3 -B test/ocudu/validate-xapp-custom-sm-capability-du.py
```

The validator creates the probe through
`deploy/ocudu/compose.xapp-custom-sm-capability.yaml` and runs it with
`docker start -a`. Resolved Compose configuration and actual image ID are
retained. The expected laboratory boundary is exactly one advertised
function, ID 2; changes stop the test for review.

No custom subscription is attempted. SDK capability JSON, RIC accepted
function IDs and absence of subscription-request markers are checked.
Cleanup removes temporary containers, restores original RAN configuration
stopped and checks unchanged baseline RIC identity.

## Retained acceptance evidence

Under `~/Work/oai-test-evidence/`:
`ocudu-custom-sm-capability-du-s5jli9u4`.

- Node 420, PLMN 001/01, role gNB-DU, component ID 0.
- SDK advertised functions: ID 2, revision 0.
- RIC accepted functions: ID 2.
- Custom model advertisement: MAC/RLC/PDCP all false.
- Subscription attempts: zero; custom delivery validation: false.
- Cleanup errors: none; baseline RIC unchanged.

Three offline classification fixtures and seven invalid-input rejection
checks passed. A static API-call check and Compose configuration check
passed before live execution. Static checks alone are not runtime proof.

Image digest pinning followed the live run; pinning itself was not another
runtime regression.

## Limitations

These separate DU/CU-UP results do not establish all OCUDU builds lack
custom models. Concurrent nodes, dynamic capability changes, process
restart and custom-SM delivery remain outside the tested scope.

The probe reports a capability snapshot; it is not a transparent adapter
for the original radio-stats xApp and does not translate KPM into custom
MAC/RLC/PDCP reports. A future supported custom ID needs identity,
subscription, payload and cleanup validation before claiming compatibility.

## CU-UP capability audit

Run the independent CU-UP validator from the repository root:

```bash
python3 -B test/ocudu/validate-xapp-custom-sm-capability-cuup.py
```

It uses `deploy/ocudu/compose.xapp-custom-sm-capability-cuup.yaml`
and the already published, digest-pinned capability image. No rebuild
or additional image publication was needed. The gNB image is also pinned.

Evidence under `~/Work/oai-test-evidence/`:
`ocudu-custom-sm-capability-cuup-z78is42m`.

- Node 420, PLMN 001/01, role gNB-CU-UP, component ID 0.
- SDK advertised ID 2, revision 0; RIC accepted ID 2.
- MAC/RLC/PDCP IDs 142/143/144 were not advertised.
- No subscriptions attempted; no custom delivery validated.
- Cleanup succeeded and baseline RIC identity remained unchanged.

DU and CU-UP were audited separately. The original radio-stats main
was neither modified nor run against unsupported models.
