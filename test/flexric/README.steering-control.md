# Python steering with multiple source nodes

## Purpose and environment

Validated on an ARM64 Raspberry Pi on 2026-10-07, Pacific time.
Connect synthetic steering recommendations to native emulator control,
selecting the source Agent through a configurable cell/CGI mapping.

Run all commands from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Requirements: Python 3, Docker Compose, sudo access, SCTP support and the
existing external oai-pi-flexric-lab bridge, subnet 172.29.0.0/24.
Stop deployments occupying the same lab addresses. Do not run unrelated
control tests concurrently: Agent log checks expect exact reception counts.
Open5GS, UERANSIM and ReDroid are outside this experiment.

## Change and identifiers

test/xapp/xapp_steering_control.py previously required the selected source
CGI to map to node 1. It now accepts source lab node IDs in 1..65535,
matching the existing native controller restriction.

The default steering_lab.json is unchanged: UE 1, cell-a CGI 256 and
cell-b CGI 512. Custom --mapping files enable other source nodes.

The demo extracts the source gNB ID as source_nr_cgi >> 8, assuming a
28-bit gNB ID inside a 36-bit CGI. This is a synthetic lab convention.
The native controller uniquely selects a matching PLMN 505/01 node.
Missing or ambiguous matches receive no control.

Examples used by the validator:

| Source node | Source CGI | Synthetic target CGI |
| --- | --- | --- |
| 1 | 256 | 512 |
| 2 | 512 | 768 |
| 3 | 768 | 1024 |

Targets need not exist for this emulator communication test.
The wrapper validates the entire input before invoking the native binary.

## Images and local validation

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Emulator | limx59/flexric-emulator:arm64-multi-agent |
| xApp | limx59/flexric-xapp:arm64-multi-agent |

Published xApp image-index digest:
sha256:fa5e6e52d37850726d7b9465d0bbbfb4ad911a29ece328d2101cec2ee6a1ca96

The previous slice-targeting upload used digest
sha256:b367777ec5193533c2428f39ab8582faaff5da1cd0f52af528141b259e326b7b.
The arm64-multi-agent tag was updated; Compose already references it.

Build the modified xApp:

```bash
sudo docker build \
  -f docker/flexric/Dockerfile \
  --target xapp --build-arg BUILD_JOBS=2 \
  -t oai-pi-flexric-xapp:steering-multi-agent-test .
```

Start the desired topology using the deployment commands below.
For local-image validation:

```bash
python3 test/flexric/validate-steering-control.py \
  --scenario multi-agent \
  --xapp-image oai-pi-flexric-xapp:steering-multi-agent-test \
  --pull-policy never \
  --output-dir /tmp/flexric-steering-local-validation
```

Use --scenario multi-ric for the dual-RIC topology.
Both local-image scenarios passed.

Publish the validated image:

```bash
sudo docker tag \
  oai-pi-flexric-xapp:steering-multi-agent-test \
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

RIC A is 172.29.0.10. Agents 1, 2 and 3 use addresses 172.29.0.20 through .22.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  up -d --no-build --pull always --force-recreate \
  ric emulator emulator-2 emulator-3
```

After Agent registration:

```bash
python3 test/flexric/validate-steering-control.py \
  --scenario multi-agent \
  --output-dir /tmp/flexric-dockerhub-steering-validation
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  down
```

## Docker Hub test: two RICs

RIC A manages nodes 1 and 2. RIC B at 172.29.0.11 manages node 3.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull always --force-recreate \
  ric ric-2 emulator emulator-2 emulator-3
```

```bash
python3 test/flexric/validate-steering-control.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-dockerhub-steering-validation
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  down
```

All experiment containers were removed.
External networks, images and the existing core deployment were preserved.

## Validator cases and checks

Each scenario first checks:

- Dry runs for source nodes 1, 2 and 3 without RIC connection.
- Rejection of source node 0 and 65536.
- Balanced input produces no recommendation or control.
- Invalid later input is rejected even when sending was requested.

The invalid-later case contains qualifying initial samples followed by an
out-of-range load. It must fail before selection or native initialization.

| Scenario | RIC | Source | Expected control result |
| --- | --- | --- | --- |
| Multi-Agent | A | Node 99 | Reject; no Agent receives control |
| Multi-Agent | A | Node 2 | Only emulator-2 receives control |
| Multi-RIC | A | Node 3 | Reject; no Agent receives control |
| Multi-RIC | A | Node 2 | Only emulator-2 receives control |
| Multi-RIC | B | Node 3 | Only emulator-3 receives control |

Successful cases require one selected recommendation with the expected
UE/source/target identifiers and executed=false, one native control request,
one successful CONTROL-ACK, and normal wrapper completion.

Per-case Agent logs start at a recorded UTC timestamp. Only the selected
Agent may log one handover-control reception and one ACK transmission.
Its logged UE ID and target CGI must match the request. Other Agents
must have no matching reception or ACK events.

The validator generates mapping and sample JSON files in a unique evidence
directory and mounts them read-only. It defaults to pulling the xApp image
from Docker Hub. Each Docker command has a 60-second timeout including pull;
the wrapper's native child timeout remains 20 seconds. Log collection has
a 30-second timeout. Cleanup attempts to remove only the temporary xApp
container created by that case.

## Results and evidence

Both local-image and Docker Hub runs passed all cases in both topologies.

- Local single RIC: /tmp/flexric-steering-local-validation/multi-agent-2bdhm7fd
- Local dual RIC: /tmp/flexric-steering-local-validation/multi-ric-dxyewifs
- Docker Hub dual RIC: /tmp/flexric-dockerhub-steering-validation/multi-ric-v7jyl292
- Docker Hub single RIC: /tmp/flexric-dockerhub-steering-validation/multi-agent-d2aa5h5a

Each directory contains generated mappings, samples, xApp output and
per-case Agent logs. Future runs use unique suffixes.
Generated evidence stays outside Git.

## Limits

Loads, cell names, CGI values and UE identity are synthetic.
The native request retains the demo's placeholder GUAMI and target CGI
representation. The emulator parses and acknowledges the request without
moving a UE. Target cells need not be deployed.

This validates policy-to-control communication and observed routing,
not real handover, cross-RIC coordination, measured load balancing or
post-control feedback. Actual OAI RC interoperability remains unvalidated.
Ambiguous-node rejection was not exercised in this live test.
