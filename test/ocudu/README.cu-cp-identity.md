# OCUDU CU-CP Agent identity validation

## Scope

This Node discovery check identifies the CU-CP Agent when DU and CU-UP
are also connected to the same FlexRIC RIC. All three records share
gNB ID `420` in the tested configuration.

## Run the comparison

Run both commands from the repository root on Raspberry Pi ARM64.
The validator uses the existing `docker_open5gs_default` network and
local gNB, RIC and xApp images. Test addresses `172.22.0.160` and
`172.22.0.163` must be available.

```bash
python3 -B test/ocudu/validate-du-cuup-identity.py
python3 -B test/ocudu/validate-du-cuup-identity.py --include-cu-cp
```

The first run leaves CU-CP E2 disabled. The second enables CU-CP E2
in a temporary gNB configuration. Each run checks one RIC snapshot
for the expected roles and removes its temporary containers.

## Acceptance and observed results

| CU-CP E2 | Expected and observed roles for gNB ID 420 |
| --- | --- |
| Disabled | One `ngran_gNB_DU` and one `ngran_gNB_CUUP`. |
| Enabled | One `ngran_gNB_DU`, one `ngran_gNB_CUUP` and one `ngran_gNB`. |

The extra `ngran_gNB` record appeared only with CU-CP E2 enabled.
Both comparison runs reported `passed: true` and `cleanup_errors: []`.
The temporary comparison and the rerun using the documented commands
produced the same node counts. All four runs passed with no cleanup errors.

| Run | Evidence directory under `~/Work/oai-test-evidence/` |
| --- | --- |
| Temporary comparison, CU-CP disabled | `ocudu-du-cuup-identity-zqz55dys` |
| Temporary comparison, CU-CP enabled | `ocudu-three-agent-identity-oou0kivv` |
| Documented command, CU-CP disabled | `ocudu-du-cuup-identity-lyghi135` |
| Documented command, CU-CP enabled | `ocudu-three-agent-identity-g21boj6a` |

Each directory contains `summary.json` and the probe logs. The
three-Agent comparison covers node identity. See the [KPM subscription targeting validation](README.subscription-targeting.md)
for the separate report-source check. The `--lifecycle` option
covers reconnection and exit cleanup for the DU/CU-UP configuration.
