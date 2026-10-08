# Multi-Agent and multi-RIC slice control

## Purpose and prerequisites

Validated on an ARM64 Raspberry Pi on 2026-10-07, Pacific time.
Select a specific emulator Agent for custom SLICE control, verify delivery
and acknowledgment, and ensure other Agents receive no control.

Run commands from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Requirements: Python 3, Docker Compose, sudo access, SCTP support and the
existing external oai-pi-flexric-lab bridge, subnet 172.29.0.0/24.
Stop other deployments occupying these addresses. Do not run unrelated
control tests concurrently: per-case log checks expect exact reception counts.
Open5GS, UERANSIM and ReDroid are outside this experiment.

| Service | Address | Node |
| --- | --- | --- |
| RIC A | 172.29.0.10 | — |
| RIC B | 172.29.0.11 | — |
| emulator | 172.29.0.20 | 1 |
| emulator-2 | 172.29.0.21 | 2 |
| emulator-3 | 172.29.0.22 | 3 |

## Source change and image

test/xapp/xapp_slice_control.py now accepts XAPP_SLICE_NODE_ID.
The default remains 1. ASCII decimal lab IDs in 1..65535 are accepted.
This range is a lab restriction, not the full protocol node-ID range.

Invalid IDs fail before RIC initialization. Selection requires exactly one
matching gNB with MCC 505, MNC 1, two MNC digits and the requested node ID.
Missing or ambiguous matches raise an error without sending control.

The existing synthetic policy proposes budgets 45/40/15 percent.
Control uses FlexRIC's custom SLICE ADD/MOD message with NVS capacity
fractions; it is not O-RAN E2SM-RC slice control.

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Emulator | limx59/flexric-emulator:arm64-multi-agent |
| xApp | limx59/flexric-xapp:arm64-multi-agent |

Published xApp image-index digest:
sha256:b367777ec5193533c2428f39ab8582faaff5da1cd0f52af528141b259e326b7b

The previous QoS-fixed xApp digest was
sha256:413acdbecc5c6cf04b878d1f3ac9de4cf1dd9a8a7bc1a4e5433228b0dc808bbf.
The existing tag was updated; Compose already references this tag.

## Build and local tests

```bash
sudo docker build \
  -f docker/flexric/Dockerfile \
  --target xapp --build-arg BUILD_JOBS=2 \
  -t oai-pi-flexric-xapp:slice-multi-agent-test .
```

Start the desired topology using the deployment commands below.
For local-image tests, run:

```bash
python3 test/flexric/validate-slice-control.py \
  --scenario multi-agent \
  --xapp-image oai-pi-flexric-xapp:slice-multi-agent-test \
  --pull-policy never \
  --output-dir /tmp/flexric-slice-local-validation
```

For the dual-RIC topology, use --scenario multi-ric.
Both local-image scenarios passed before publication.

```bash
sudo docker tag \
  oai-pi-flexric-xapp:slice-multi-agent-test \
  limx59/flexric-xapp:arm64-multi-agent
```

```bash
sudo docker push limx59/flexric-xapp:arm64-multi-agent
```

## Docker Hub test: single RIC, three Agents

Remove local image overrides before reproducing the published-image test:

```bash
unset FLEXRIC_RIC_IMAGE FLEXRIC_EMULATOR_IMAGE FLEXRIC_XAPP_IMAGE
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  up -d --no-build --pull always --force-recreate \
  ric emulator emulator-2 emulator-3
```

After Agent registration:

```bash
python3 test/flexric/validate-slice-control.py \
  --scenario multi-agent \
  --output-dir /tmp/flexric-dockerhub-slice-validation
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  down
```

## Docker Hub test: two RICs

RIC A manages nodes 1 and 2. RIC B manages node 3.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull always --force-recreate \
  ric ric-2 emulator emulator-2 emulator-3
```

```bash
python3 test/flexric/validate-slice-control.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-dockerhub-slice-validation
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  down
```

All experiment containers were removed after validation.
External networks, images and the existing core deployment were preserved.

## Cases and checks

Both scenarios first reject six invalid IDs: empty, 0, -1, abc, 65536
and an overflowing decimal value. These cases use --network none and must
exit with the validation message before any E42 Setup request.

| Scenario | RIC | Requested node | Expected result |
| --- | --- | --- | --- |
| Multi-Agent | A | 99 | Reject; no Agent receives control |
| Multi-Agent | A | Default 1 | Only emulator receives control and sends ACK |
| Multi-Agent | A | 2 | Only emulator-2 receives control and sends ACK |
| Multi-RIC | A | 3 | Reject; no Agent receives control |
| Multi-RIC | A | 2 | Only emulator-2 receives control and sends ACK |
| Multi-RIC | B | 3 | Only emulator-3 receives control and sends ACK |

For each successful case, the validator checks:

- Selected node message and exactly one control transmission.
- Exactly one successful CONTROL-ACK response.
- Proposed budgets of 45/40/15 percent in the xApp output.
- One SLICE CONTROL ADD rx and one CONTROL ACKNOWLEDGE tx at the target.
- No matching reception or ACK events at the other Agents.

Each case captures Agent logs from a UTC timestamp taken before execution.
The validator defaults to pulling the xApp from Docker Hub.
Docker execution has a 60-second timeout including pulling; log collection
has a 30-second timeout. Temporary xApp containers have unique names and
cleanup attempts to remove only the container created for that case.
RIC and Agent containers require explicit Compose cleanup.

Both local-image and published-image scenarios passed all cases.

## Local evidence

- Local single RIC: /tmp/flexric-slice-local-validation/multi-agent-lonoag5c
- Local dual RIC: /tmp/flexric-slice-local-validation/multi-ric-m3qguqgd
- Docker Hub dual RIC: /tmp/flexric-dockerhub-slice-validation/multi-ric-_tpesy7j
- Docker Hub single RIC: /tmp/flexric-dockerhub-slice-validation/multi-agent-f42p7bxc

Directories contain invalid-ID logs, per-case xApp logs and per-case logs
for all three Agents. Future runs use unique directory suffixes.
Generated evidence remains outside Git.

## Limits

The emulator accepts and acknowledges the message without applying or
retaining scheduler changes. Proposed percentages and capacity fractions
do not establish enforced PRB allocation or workload isolation.

Reception checks establish observed target routing, not correctness of every
encoded payload field. Ambiguous-target rejection exists in the source but
was not exercised by a duplicate-node live test.

OAI scheduler integration, real slice enforcement, cross-RIC coordination,
control failure recovery and real UE performance remain unvalidated.
