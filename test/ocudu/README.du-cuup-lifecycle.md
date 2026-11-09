# OCUDU RIC/Agent reconnection and exit cleanup

## Scope

This Node discovery test uses one temporary FlexRIC RIC and one
OCUDU gNB with DU and CU-UP E2 enabled. It verifies reconnection after
a RIC restart, node record removal after a graceful gNB stop, and
registration after the gNB starts again.

## Run the test

Run from the repository root on Raspberry Pi ARM64. The validator
uses the existing `docker_open5gs_default` network and the local gNB,
RIC and xApp images referenced by the script. Test addresses
`172.22.0.160` and `172.22.0.163` must be available.

```bash
python3 -B test/ocudu/validate-du-cuup-identity.py --lifecycle
```

## Acceptance and results

The probe takes a fresh node snapshot after E42 Setup at each stage.
The node counts below apply to gNB ID `420`.

| Stage | Expected and observed result |
| --- | --- |
| Initial connection | One DU record and one CU-UP record. |
| RIC restart | Both records return while the original gNB process stays running. |
| Graceful gNB stop | Both records disappear while the RIC process stays running. |
| gNB start | Both records return with a new gNB process in the same container. The RIC process stays running. |

The Raspberry Pi run reported `passed: true` and `cleanup_errors: []`.
The validator removed both temporary containers. Exit cleanup was
verified for a graceful gNB stop.

## Evidence

The evidence directory on the Raspberry Pi is
`~/Work/oai-test-evidence/ocudu-du-cuup-identity-g6gvho0o/`.
`summary.json` and `lifecycle.json` contain process identities and
node snapshots. Probe logs retain the E42 Setup and enumeration
output for each stage.
