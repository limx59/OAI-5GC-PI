# Integrated regression: testmode state verification

## Status and scope

Passed within the parsed/autoderived configuration-state matrix and retained
normal-UE evidence-linkage scope. This is an item under the existing
**Integrated regression** test case.

The checker runs the existing gNB configuration parser, autoderivation and
validation, prints selected state fields and exits before initialization.
It does not create test UEs, initialize a radio or establish a new core session.

## State definitions

DU testmode is enabled when `test_mode.test_ue.rnti` differs from
`INVALID_RNTI` (0 in the checked configuration). DU enablement automatically
sets CU-CP AMF `no_core=true`.

CU-UP uses the independent `cu_up.test_mode.enable` flag. The reported
`no_core` field is specifically CU-CP AMF state, not every no-core setting
in the application.

| Case | DU enabled | RNTI | CU-UP enabled | CU-CP no_core |
| --- | --- | --- | --- | --- |
| Default | false | 0 | false | false |
| Explicit DU disabled | false | 0 | false | false |
| DU enabled | true | 17921 | false | true |
| Explicit CU-UP disabled | false | 0 | false | false |
| CU-UP enabled | false | 0 | true | false |
| Both enabled | true | 17921 | true | true |
| Retained normal-UE configuration | false | 0 | false | false |

The enabled DU branch uses dummy upper-layer timers according to the inspected
source. This dry-run experiment does not execute or validate that runtime branch.

## Image and Compose operation

Image: `limx59/oai-pi-ocudu-testmode-state:arm64-config-state-test`.

The image extends the validated configuration checker. The additional patch
is applied only to Docker build source; host third-party source is unchanged.
It prints `LAB_TESTMODE_STATE` immediately before
`LAB_CONFIG_VALIDATION_PASSED`.

Build:

```bash
sudo docker compose \
  -f "$HOME/Work/oai-5gc-pi-review/deploy/ocudu/compose.testmode-state-build.yaml" \
  build testmode-state
```

Run:

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/validate-testmode-state-compose.py"
```

The validator generates private configurations and starts each checker through
Compose with `--dryrun` and a bounded timeout. Services have no network,
devices or Docker socket. They use a read-only filesystem, a read-only
configuration mount and the host UID/GID to read private 0600 files.

The seventh case currently requires the retained local experiment
`ocudu-slice-online-ul-drain-xadw8l91`, including its original summary and
`config/gnb.yml`. These private files are not shipped in Git. Reproduction
of this linkage check requires that evidence archive; the first six cases
are generated from the tracked base configuration.

## Evidence and independent review

The seven-case run `ocudu-testmode-state-thti9m_t` passed. Each case retains
configuration content/hash, stdout/stderr and container image/exit metadata.
The parent summary retains baseline continuity and cleanup results.

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/review-testmode-state.py" \
  --evidence /absolute/path/to/retained/state-check-run
```

The historical configuration replay exactly matches its original recorded
hash. Historical logs contain NG setup, UE RRC/registration/PDU-session
records, three successful 5/5 UPF ping checks and four `test_mode=false`
fields. Those four log fields are supporting evidence and are not individually
mapped to the DU/CU-UP switches.

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/validate-testmode-evidence.py" \
  --evidence /absolute/path/to/retained/state-check-run
```

Six in-memory mutations were rejected: wrong parsed state, missing validation
marker, changed configuration, wrong historical linkage, failed UPF ping and
a true testmode field in the historical log. Original evidence is unchanged.

The Docker Hub image tag was pushed and pulled with matching image identity.
Runtime configuration uses the tag; evidence records the actual image ID.

## Limits

The checker image differs from the historical running gNB image.
Configuration replay and historical access evidence support the documented
normal-UE path; they do not inspect the historical process's internal flags.
This item does not validate actual test-UE creation, standalone DU stub-CU
operation, CU-UP synthetic traffic behavior, dummy-timer behavior, sustained
sessions or physical RF.

Private generated configurations and raw evidence must not be committed.
