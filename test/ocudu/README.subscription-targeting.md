# OCUDU KPM subscription targeting

## Scope

This Node discovery check verifies that an xApp can select DU, CU-UP
and CU-CP individually while all three are connected to the same
FlexRIC RIC. All three use gNB ID `420` and advertise KPM RAN
Function ID `2`. CU-CP appears as `ngran_gNB` in this configuration.

## Run the test

Run from the repository root on Raspberry Pi ARM64. The validator
uses the existing `docker_open5gs_default` network, local test images
and the lab UE configuration. Test addresses `172.22.0.160`,
`172.22.0.161` and `172.22.0.163` must be available.

```bash
python3 -B test/ocudu/validate-du-cuup-identity.py --subscription-targeting
```

The validator starts a temporary RIC, gNB and UE. It creates
`xapp-du.conf`, `xapp-cuup.conf` and `xapp-cucp.conf` in the evidence
directory and mounts the selected file read-only for each probe.
The repository xApp configuration is read as a template.

## Acceptance and results

Each probe enumerates all three Agents, selects the target by gNB ID
and role, and submits a KPM subscription using the selected node ID.
It requires at least three reports with the expected gNB ID and role.
The run fails if the probe observes an unexpected source or reports
a cleanup error.

| Target | KPM style | Metric | Matching reports |
| --- | ---: | --- | ---: |
| DU (`ngran_gNB_DU`) | 4 | `DRB.UEThpDl` | 3 |
| CU-UP (`ngran_gNB_CUUP`) | 1 | `DRB.PacketSuccessRateUlgNBUu` | 3 |
| CU-CP (`ngran_gNB`) | 1 | `RRC.ConnEstabAtt` | 3 |

The fixed Python entry point passed on Raspberry Pi. Each probe
reported an empty `unexpected_sources` list. The final summary
reported `passed: true` and `cleanup_errors: []`, and all three
temporary containers were removed. The test covers sequential
subscriptions and report-source matching.

## Evidence

The Raspberry Pi evidence directory is
`~/Work/oai-test-evidence/ocudu-three-agent-identity-5sdyz2ym/`.
It contains `subscription-targeting.json`, `summary.json`, the
role-specific configurations and the probe logs.
