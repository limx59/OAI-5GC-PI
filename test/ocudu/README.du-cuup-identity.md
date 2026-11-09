# OCUDU DU/CU Agent identity validation

## Scope

Verify that one FlexRIC RIC can distinguish the OCUDU DU and CU-UP
agents when both connect with the same gNB ID. This test belongs to
Node discovery.

## Run the test

Run from the repository root on Raspberry Pi ARM64. The validator
requires the existing `docker_open5gs_default` network, the local gNB,
RIC and xApp images referenced by the script, and free test addresses
`172.22.0.160` and `172.22.0.163`.

```bash
python3 -B test/ocudu/validate-du-cuup-identity.py
```

The validator enables DU and CU-UP E2 in a temporary gNB configuration,
starts a dedicated gNB and RIC, and uses an xApp probe to enumerate
connected E2 nodes. It reuses existing images and removes the temporary
containers after the test.

## Acceptance and result

A single `conn_e2_nodes()` snapshot must contain exactly one
`ngran_gNB_DU` and one `ngran_gNB_CUUP` for gNB ID `420`. The run must
finish with `cleanup_errors` empty.

| gNB ID | E2 node role | Observed count |
| --- | --- | ---: |
| 420 | `ngran_gNB_DU` | 1 |
| 420 | `ngran_gNB_CUUP` | 1 |

The Raspberry Pi run reported `passed: true` and `cleanup_errors: []`.
Both temporary containers were removed. The report is retained at
`~/Work/oai-test-evidence/ocudu-du-cuup-identity-wrw6zkp2/summary.json`.

RIC/Agent reconnection and removal of an Agent's node record while
the RIC stays running remain separate Node discovery checks.
