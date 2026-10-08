# FlexRIC multi-agent and multi-RIC integration tests

Run commands from the repository root. Python 3, Docker, Docker Compose,
sudo access and host SCTP support are required.

The validator checks an already running emulator topology. Its control
check sends emulator handover requests; it does not perform real handover.
Do not run unrelated control tests concurrently: reception checks expect
exactly one request at the selected Agent during the validation window.

## Images

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Emulator | limx59/flexric-emulator:arm64-multi-agent |
| xApps | limx59/flexric-xapp:arm64-multi-agent |

Published image-index digests for the validated upload:

| Component | Digest |
| --- | --- |
| Emulator | sha256:24d8510c75501d02496247a21967c55e48696d54f0208c88d3131c60807c4236 |
| xApps | sha256:aec1fb4b061a53a11a653df0b622b0167135e6195cdaccb831a9dfe215779bd3 |

The topology overrides retain build settings and default to Docker Hub
images. FLEXRIC_EMULATOR_IMAGE and FLEXRIC_XAPP_IMAGE can override those
names for local testing. Tags are mutable; pull explicitly before deployment.

The emulator accepts FLEXRIC_EMULATOR_NB_ID as a decimal integer in
1..65535. This is a lab-specific validation range, not the protocol's full
gNB ID range. If unset, the compiled default remains unchanged.

## Network

These tests share the external oai-pi-flexric-lab bridge, 172.29.0.0/24.
Check subnet conflicts before creating it:

```bash
sudo docker network create --driver bridge \
  --subnet 172.29.0.0/24 oai-pi-flexric-lab
```

Stop other deployments using the same addresses before running these tests.
No host ports are published; the existing Open5GS network is not required.

| Service | Address | Node ID |
| --- | --- | --- |
| RIC A | 172.29.0.10 | — |
| RIC B, dual-RIC scenario only | 172.29.0.11 | — |
| emulator | 172.29.0.20 | 1 |
| emulator-2 | 172.29.0.21 | 2 |
| emulator-3 | 172.29.0.22 | 3 |

## Single RIC with three Agents

Pull one service for each distinct image:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  --profile tools pull ric emulator xapp-nodes
```

Start from registry images without building:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  up -d --no-build --pull always ric emulator emulator-2 emulator-3
```

Allow E2 setup to complete, then validate:

```bash
python3 test/flexric/validate-topology.py \
  --scenario multi-agent \
  --checks config invalid-id nodes kpm control \
  --output-dir /tmp/flexric-multi-agent-validation
```

Expected results: nodes 1, 2 and 3 are discovered and report KPM.
Control for node 2 reaches only emulator-2, with target CGI 768.
A request for absent node 99 fails without transmitting control.

Stop the topology:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml down
```

## Two RICs with separate Agent groups

Use all three Compose files. RIC A manages nodes 1 and 2; RIC B manages
node 3. RIC B configuration is under deploy/oai-flexric/config/multi-ric.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  --profile tools pull ric emulator xapp-nodes
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull always \
  ric ric-2 emulator emulator-2 emulator-3
```

Allow E2 setup to complete, then validate:

```bash
python3 test/flexric/validate-topology.py \
  --scenario multi-ric \
  --checks config invalid-id nodes kpm control \
  --output-dir /tmp/flexric-multi-ric-validation
```

Expected results: RIC A discovers and reports only nodes 1 and 2;
RIC B discovers and reports only node 3. The two KPM xApps run concurrently
and receive subscription deletion responses.

RIC A rejects control for node 3 without transmitting a request. RIC B
routes it to emulator-3, with target CGI 1024; the other Agents receive no
control during the validation window.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml down
```

## Local source builds

Build settings remain available. Building locally does not publish images:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  --profile tools build emulator xapp-nodes
```

To use those local builds, start with --no-build --pull never.
For separately tagged images, set FLEXRIC_EMULATOR_IMAGE and
FLEXRIC_XAPP_IMAGE when starting Compose, and pass matching
--emulator-image and --xapp-image options to the validator.

## Script behavior and evidence

Use --help to list checks. Invalid-ID checks start short-lived containers
with networking disabled. Other checks expect the selected topology to
be running. The control target is selected by lab PLMN 505/01 and the
28-bit gNB ID extracted from the source CGI; absent or ambiguous matches
are rejected. The Python steering demo still restricts its mapping to
node 1; the validator invokes the native control binary directly.

Each check saves output under --output-dir. Repeating a scenario in the
same directory overwrites its previous check logs. Failures exit nonzero.
These logs are local artifacts and should not be committed.

Both topologies were validated on an ARM64 Raspberry Pi on 2026-10-07,
first with local builds and then with pulled Docker Hub images. Container
image references and repository digests were checked. Test containers
were removed afterward.

Validation covers distinct node registration, emulator KPM reports,
subscription cleanup, selected control routing and missing-node rejection.
The two RICs share a bridge: this demonstrates application-level grouping,
not network security isolation, RIC federation or shared state.

Agent migration between RICs, simultaneous connections from one Agent
to multiple RICs, RIC failover, automatic subscription restoration and
OAI RC interoperability remain unvalidated. Emulator metrics are synthetic.

If terminal echo or newline handling changes, restore it with:

```bash
stty sane echo opost onlcr
```

## Agent recreation and xApp connection cleanup

The multi-agent and multi-RIC overlays now default to
limx59/flexric-ric:arm64-multi-agent. FLEXRIC_RIC_IMAGE can override the RIC
image for local development. The base single-emulator deployment retains
its original image setting.

Validated RIC image-index digest:

sha256:3574ec908944e75cc569cfb2326e6f1c3506d58682d464dd04d34cbd69c0aee4

An initial Agent 2 recreation test failed with the original RIC image:
the Agent retried E2 Setup after receiving no response, and the RIC aborted
when registering the duplicate node ID. The Agent then aborted as well.

The RIC changes enable normal xApp SCTP shutdown notifications, remove
disconnected xApps from the connection map, and send node updates to actual
registered xApp IDs. Node-update sends use the existing SCTP association
and are nonblocking. The generated node array is freed after notification.
Failed node-update sends are logged; this path does not retry them.

Start the desired topology using the Docker Hub workflow above, then run
the recovery test. The script stops and recreates emulator-2 while leaving
the RIC containers running.

Single RIC:

```bash
python3 test/flexric/validate-agent-recovery.py \
  --scenario multi-agent \
  --output-dir /tmp/flexric-agent-recovery-single
```

Dual RIC:

```bash
python3 test/flexric/validate-agent-recovery.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-agent-recovery-dual
```

The test verifies baseline discovery and KPM, disappearance of node 2,
rediscovery after recreation, and fresh KPM subscriptions after recovery.
It checks that the RIC container identities are unchanged and that the
containers are running at the final inspection. The topology remains
running after the test; use the corresponding cleanup command above.

On 2026-10-07, single-RIC and dual-RIC recovery passed with the local fixed
RIC image. Dual-RIC recovery also passed after pulling the published image.
Both running RIC image references and the published digest were checked.
The existing targeted-control test passed with the fixed dual-RIC topology.

Evidence directories and logs:

- /tmp/flexric-agent-recovery-fixed-single
- /tmp/flexric-agent-recovery-fixed-dual
- /tmp/flexric-agent-recovery-fixed-control
- /tmp/flexric-agent-recovery-fixed-events.log
- /tmp/flexric-dockerhub-agent-recovery-dual

The local dual-RIC event log recorded 12 xApp disconnections and no matching
assertion or send-error messages. Experiment containers were removed after
validation.

These tests cover normal xApp shutdown and one Agent recreation per run.
They do not validate abrupt xApp failure, active subscription cleanup on
disconnect, automatic restoration of an existing subscription, RIC
failover, or handling of arbitrary duplicate E2 Setup requests.
A timed-out Compose client may leave its one-off xApp container running;
inspect the experiment containers and clean them up before another run.

## Agent recovery experiment

See [Agent recreation experiment](README.agent-recovery.md) for the initial failure, source changes, build and
Docker Hub publication, recovery validation, evidence and cleanup.

## Multi-agent and multi-RIC KPM CSV recording

See [the KPM CSV recording guide](README.kpm-recording.md) for Docker Hub deployment steps, reusable validation, observed results and cleanup.
