# Embedded dual-node online advisory

## Status

Passed for the documented same-host Raspberry Pi ARM64 experimental platform:
two OCUDU DU nodes, two OAI NR UEs, FlexRIC and the existing Open5GS core.

Accepted published-image run:
`ocudu-embedded-online-published-v2-174d5vuw`.

Online recommendations passed in both directions. No migration or E2 control
was executed. Synchronized collection windows, physical RF operation and
long-term stability remain outside this acceptance scope.

## Laboratory policy

Configuration: `config/steering-dual-node-embedded-async.json`.

- Source PRB load: at least 30%.
- Target PRB load: at most 10%.
- Load difference: at least 20 percentage points.
- Two consecutive independent qualifying pairs.
- Recommendation cooldown: 30 seconds.
- Source receipt age at decision time: at most 7 seconds.
- Query timestamp skew: at most 1 second.
- Explicit asynchronous latest-unused-source observation mode.
- Source receipt alignment is not required.
- Control execution is disabled.

These are laboratory calibration parameters, not production capacity limits.
Repeated cached source batches do not count as independent observations.
Rejected or balanced evaluations reset the candidate sequence.
Receipt freshness does not establish collection-window freshness.

## Provenance

Five laboratory KPM measurements carry source revision, source receipt
timestamp and query timestamp. Timestamps use integer seconds and microsecond
remainders to avoid ASN.1 REAL precision loss.

The revision measurement must be requested first to snapshot query time.
The existing Style 4 whole-row measurement lock protects metadata and PRB
reads. Source receipt timestamps matched diagnostic records exactly in the
integer metadata validation run.

The clock assumptions apply to the documented same-host Linux setup.
Distributed hosts, different time namespaces, source restarts and multiple
UE rows require additional validation.

## Run

From the review repository root, execute:

`python3 -B test/ocudu/validate-steering-embedded-online-published-v2.py`

Prerequisites include the existing core and baseline RIC, the expected
patched AMF/AUSF image identities, two distinct private UE configurations,
available test addresses, at least 3 GiB available memory and all merged
Compose images present locally.

The validator creates a dedicated bounded project. It preserves shared core
and baseline RIC identities and cleans up only its own test resources.

Two concurrent connectivity rounds send five single-request probes per UE.
Each request has a 3-second response budget; all twenty probes must pass.
No retries are added.

Five 20-second downlink phases use these offered rates in Mbit/s:

| Phase | Node 420 | Node 421 |
| --- | --- | --- |
| low-before | 0.2 | 0.2 |
| node-420-3M | 3 | 0.2 |
| low-middle | 0.2 | 0.2 |
| node-421-3M | 0.2 | 3 |
| low-after | 0.2 | 0.2 |

Receiver throughput must be within 80-120% of the offered rate and loss
at most 5%. These checks are separate from PRB policy thresholds.

## Accepted results

- 366 KPM reports: 180 from node 420 and 186 from node 421.
- 50 and 52 independent source batches, respectively.
- Online recommendation 420 to 421 at PRB loads 96%/5%.
- Online recommendation 421 to 420 at PRB loads 78%/1%.
- Two independent qualifying pairs for each recommendation.
- Four cooldown evaluations.
- No admitted source-batch reuse or control execution.
- Shared core and baseline RIC identities unchanged.
- No cleanup errors.

## Published image digests

gNB repository: `limx59/oai-pi-ocudu-gnb`
Tag: `arm64-steering-prb-kpm-metadata-v2-test`
Digest: `sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b`

xApp repository: `limx59/oai-pi-ocudu-flexric-xapp`
Tag: `arm64-steering-embedded-online-test`
Digest: `sha256:502b970b4c20285e1ad8cd17ac6536cfc99d482d4cf834ae40b2427a9e5c7561`

Both published images were inspected for linux/arm64 and pulled by digest.
The published validator pins these references.

## Evidence

Evidence remains below `test/ocudu/.local/evidence/`.
Review summary.json, advisory.jsonl, kpm.csv and private diagnostics.
The validator summary's online_advisory_acceptance section establishes
online acceptance; producer placeholder flags alone do not.

Do not commit private subscriber configurations, raw logs, local evidence,
backup files or build output.

The xApp Dockerfile currently requires a local dual-node base image for
rebuilding. Runtime validation uses the published final images above.
