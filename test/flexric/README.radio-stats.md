# Multi-node MAC/RLC/PDCP reporting

## Purpose and prerequisites

Validated on an ARM64 Raspberry Pi on 2026-10-07, Pacific time.
Check custom MAC, RLC and PDCP subscriptions, report node attribution,
record counts, timestamps and subscription deletion responses.

Run commands from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Requirements: Python 3, Docker Compose, sudo access, SCTP support and the
existing external oai-pi-flexric-lab bridge, subnet 172.29.0.0/24.
Stop deployments occupying the same lab addresses before starting.
The existing Open5GS, UERANSIM and ReDroid deployment is outside this test.

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Emulator | limx59/flexric-emulator:arm64-multi-agent |
| xApp | limx59/flexric-xapp:arm64-multi-agent |

The xApp upload used image-index digest
sha256:413acdbecc5c6cf04b878d1f3ac9de4cf1dd9a8a7bc1a4e5433228b0dc808bbf.
No source or image changes were required for this experiment.
The new host-side validator reuses xapp_radio_stats.py in the image.

Remove local image overrides when reproducing the published-image test:

```bash
unset FLEXRIC_RIC_IMAGE FLEXRIC_EMULATOR_IMAGE FLEXRIC_XAPP_IMAGE
```

## Single RIC with three Agents

RIC A is 172.29.0.10. Nodes 1, 2 and 3 use Agent addresses
172.29.0.20, 172.29.0.21 and 172.29.0.22.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  up -d --no-build --pull always --force-recreate \
  ric emulator emulator-2 emulator-3
```

After Agent registration:

```bash
python3 test/flexric/validate-radio-stats.py \
  --scenario multi-agent \
  --output-dir /tmp/flexric-dockerhub-radio-stats
```

Expected: nine model/node pairs and nine subscription deletion responses.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  down
```

## Two RICs with separate Agent groups

RIC A manages nodes 1 and 2. RIC B at 172.29.0.11 manages node 3.
The validator runs one monitoring xApp per RIC, sequentially.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull always --force-recreate \
  ric ric-2 emulator emulator-2 emulator-3
```

```bash
python3 test/flexric/validate-radio-stats.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-dockerhub-radio-stats
```

Expected: six model/node pairs for A and three for B, with corresponding
subscription deletion responses.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  down
```

All experiment containers were removed after validation.
External networks, images and the existing core deployment were preserved.

## Checks and evidence

The validator defaults to Docker Hub and --pull-policy always.
Use --xapp-image and --pull-policy never for explicit local-image tests.

Each group creates a temporary xApp container and a unique evidence directory.
The xApp subscribes to configured custom models at 100 ms and monitors for
ten seconds after subscription setup. Docker execution, including image
pulling, has a 60-second timeout.

Validation checks:

- Successful xApp exit and absence of known callback errors or assertions.
- Exactly one subscription per expected model/node pair.
- At least two parsed reports per expected model/node pair.
- Positive integer timestamps and nonnegative record counts.
- One subscription deletion response per expected model/node pair.

The validator prints report totals, nonempty report totals and minimum/maximum
record counts. Empty lists are allowed: delivery success alone does not prove
that statistical records are available. A completely empty run is labeled
explicitly in the output.

Logs stream to disk. Cleanup attempts to remove only the temporary xApp
container created by this test. RIC and Agent containers require the explicit
Compose cleanup above. Partial logs after failure are not passing results.

## Observed single-RIC results

| Model | Nodes | Reports per node | Nonempty per node | Record count range |
| --- | --- | --- | --- | --- |
| MAC | 1, 2, 3 | 100 | 73 | 0–5 |
| PDCP | 1, 2, 3 | 100 | 73 | 0–5 |
| RLC | 1, 2, 3 | 100 | 90 | 0–3 |

All nine model/node pairs passed. Subscription cleanup was complete.

## Observed dual-RIC results

| RIC | Model | Node | Reports | Nonempty | Record count range |
| --- | --- | --- | --- | --- | --- |
| A | MAC | 1 | 100 | 70 | 0–9 |
| A | MAC | 2 | 100 | 70 | 0–9 |
| A | PDCP | 1 | 99 | 69 | 0–9 |
| A | PDCP | 2 | 100 | 70 | 0–9 |
| A | RLC | 1 | 100 | 70 | 0–3 |
| A | RLC | 2 | 100 | 70 | 0–3 |
| B | MAC | 3 | 100 | 80 | 0–8 |
| B | PDCP | 3 | 100 | 80 | 0–8 |
| B | RLC | 3 | 100 | 93 | 0–2 |

Both groups passed and subscription cleanup was complete.
The validator does not require identical or exactly 100 report counts.
The reason for the observed 99 versus 100 difference was not established.

Local evidence directories:

- /tmp/flexric-dockerhub-radio-stats/multi-agent-2aafqkij
- /tmp/flexric-dockerhub-radio-stats/multi-ric-2rxpf_us

Single-RIC evidence contains ric-a-radio.log. Dual-RIC evidence also
contains ric-b-radio.log. Future runs use unique directory suffixes.
Generated logs remain outside Git.

## Limits

Earlier single-Agent validation observed empty record lists. These new
runs received nonempty lists; the reason for that difference was not
established.

Records come from the emulator and are synthetic. This experiment checks
reported identities and list lengths, not the correctness of individual
MAC/RLC/PDCP fields, real UE identities, or actual radio performance.
Identical counts across some nodes do not establish independent workloads.

OAI interoperability and nonempty OAI records remain unvalidated.
The dual-RIC run checks observed node separation, not security isolation
or RIC federation. Automatic subscription recovery was not tested.
