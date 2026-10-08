# Multi-agent and multi-RIC KPM CSV recording

## Purpose and prerequisites

Validated on an ARM64 Raspberry Pi on 2026-10-07, local Pacific time.
Record emulator KPM measurements as CSV and verify node identities,
DL/UL metric coverage, numeric values and subscription deletion responses.

Run commands from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Python 3, Docker Compose, sudo access, SCTP support and the existing external
oai-pi-flexric-lab bridge are required. The bridge uses 172.29.0.0/24.
Stop deployments occupying the same lab addresses before starting.
Open5GS, UERANSIM and ReDroid are outside this experiment.

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Emulator | limx59/flexric-emulator:arm64-multi-agent |
| xApp | limx59/flexric-xapp:arm64-multi-agent |

Compose retains build settings, but these commands use --no-build and
--pull always. The validator also explicitly pulls its xApp image.
No new image build or upload was required for this experiment.

Remove local image overrides when reproducing the published-image test:

```bash
unset FLEXRIC_RIC_IMAGE FLEXRIC_EMULATOR_IMAGE FLEXRIC_XAPP_IMAGE
```

## Single RIC with three Agents

Start RIC A at 172.29.0.10 and Agents 1, 2 and 3 at
172.29.0.20, 172.29.0.21 and 172.29.0.22:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  up -d --no-build --pull always --force-recreate \
  ric emulator emulator-2 emulator-3
```

Run the recorder validation after Agent registration:

```bash
python3 test/flexric/validate-kpm-recording.py \
  --scenario multi-agent \
  --output-dir /tmp/flexric-dockerhub-kpm-recording
```

Expected: one passing RIC group containing nodes 1, 2 and 3.

Clean up before switching scenarios:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  down
```

## Two RICs with separate Agent groups

RIC A manages nodes 1 and 2. RIC B at 172.29.0.11 manages node 3.
The xApps connect to each RIC sequentially and produce separate CSV files.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull always --force-recreate \
  ric ric-2 emulator emulator-2 emulator-3
```

```bash
python3 test/flexric/validate-kpm-recording.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-dockerhub-kpm-recording
```

Expected: RIC A reports only nodes 1 and 2; RIC B reports only node 3.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  down
```

Both experiment topologies were removed after validation.
The external bridge, published images and existing core deployment remain.

## Validator behavior

The script requires an already running topology. It creates a unique
evidence directory and one temporary xApp container per RIC group.
The recorder subscribes to matching nodes and monitors for ten seconds
after subscription setup. Docker execution, including image pulling,
has a 60-second timeout.

Each xApp log must show the expected subscribed node set, successful exit,
and one subscription delete response per expected node. Known callback
errors, mismatched measurement rows and unsupported formats fail validation.

CSV checks require:

- A nonempty file with the required columns.
- The expected node IDs and PLMN 505/1.
- DRB.UEThpDl and DRB.UEThpUl for every expected node.
- Indication format 1 or 3, with complete numeric measurements.
- Finite, nonnegative throughput values and UTC receipt timestamps.

The script prints record counts per node and metric. It does not require
equal counts or an exact total. Fresh output directories and the recorder's
exclusive file creation protect earlier experiment data.

Logs are streamed to disk, including during a timeout. Cleanup attempts to
remove only the temporary xApp container created by the validator.
A failed or interrupted test may leave a partial CSV; inspect the evidence
before interpreting it. RIC and Agent containers remain for explicit cleanup.

## Observed results

Both scenarios passed with the Docker Hub images.

| Scenario | RIC | Node | DL records | UL records |
| --- | --- | --- | --- | --- |
| Multi-agent | A | 1 | 26 | 26 |
| Multi-agent | A | 2 | 33 | 33 |
| Multi-agent | A | 3 | 33 | 33 |
| Multi-RIC | A | 1 | 26 | 26 |
| Multi-RIC | A | 2 | 26 | 26 |
| Multi-RIC | B | 3 | 26 | 26 |

The single-RIC CSV contained 184 rows. The dual-RIC CSV files contained
104 rows for RIC A and 52 rows for RIC B. All checked rows passed validation
and all expected subscription deletion responses were received.

Local evidence directories:

- /tmp/flexric-dockerhub-kpm-recording/multi-agent-m_bx2b07
- /tmp/flexric-dockerhub-kpm-recording/multi-ric-umt3id3x

Each directory contains ric-a.log and ric-a.csv. The dual-RIC directory
also contains ric-b.log and ric-b.csv. Future runs use different directory
suffixes. Generated logs and CSV files must stay outside Git.

## Limits

Measurements are synthetic emulator data. This experiment does not measure
OAI UE traffic, throughput accuracy, durable storage performance or real
handover. CSV timestamps are receipt times; UE report indexes are local to
an indication and are not persistent UE identities.

The dual-RIC test checks the observed node separation, not security isolation,
RIC federation or simultaneous recorder execution. It does not test automatic
subscription recovery. Published tags are mutable; consult the image digests
documented in README.md when reproducing a specific release.
