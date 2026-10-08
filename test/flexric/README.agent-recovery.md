# FlexRIC Agent recreation experiment

## Purpose and validated scope

Experiment date: 2026-10-07. Platform: ARM64 Raspberry Pi.

Validate that an emulator E2 Agent can be recreated while its RIC remains
running, then rediscovered and used by fresh KPM subscriptions.

| Scenario | RIC A nodes | RIC B nodes | Validation |
| --- | --- | --- | --- |
| Single RIC | 1, 2, 3 | Not deployed | Local fixed RIC image |
| Dual RIC | 1, 2 | 3 | Local fixed and published RIC images |

Agent 2 is the recreated service in both scenarios. This experiment does
not establish automatic restoration of an existing xApp subscription.

Run the commands below from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Python 3, Docker Compose, sudo access and host SCTP support are required.
The existing Open5GS, UERANSIM and ReDroid deployment is outside this test.

## 1. Network and images

The external bridge is oai-pi-flexric-lab, subnet 172.29.0.0/24.

| Service | Address | Node ID |
| --- | --- | --- |
| ric | 172.29.0.10 | — |
| ric-2 | 172.29.0.11 | — |
| emulator | 172.29.0.20 | 1 |
| emulator-2 | 172.29.0.21 | 2 |
| emulator-3 | 172.29.0.22 | 3 |

Check the existing network and address use:

```bash
sudo docker network inspect oai-pi-flexric-lab \
  --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

If the network is absent, check subnet conflicts and create it once:

```bash
sudo docker network create --driver bridge \
  --subnet 172.29.0.0/24 oai-pi-flexric-lab
```

Stop other deployments using the same lab addresses before proceeding.

| Component | Published image | Image-index digest |
| --- | --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent | sha256:3574ec908944e75cc569cfb2326e6f1c3506d58682d464dd04d34cbd69c0aee4 |
| Emulator | limx59/flexric-emulator:arm64-multi-agent | sha256:24d8510c75501d02496247a21967c55e48696d54f0208c88d3131c60807c4236 |
| xApps | limx59/flexric-xapp:arm64-multi-agent | sha256:aec1fb4b061a53a11a653df0b622b0167135e6195cdaccb831a9dfe215779bd3 |

The overlays retain build settings. Their defaults use Docker Hub images.
FLEXRIC_RIC_IMAGE, FLEXRIC_EMULATOR_IMAGE and FLEXRIC_XAPP_IMAGE override
image names. Unset local overrides when validating the published defaults.

## 2. Initial failure and diagnosis

The first recovery experiment used limx59/flexric-ric:arm64, before the
RIC fix. Baseline node discovery and KPM passed. Stopping Agent 2 removed
node 2 from the RIC's advertised node list.

After Agent 2 recreation:

1. At 23:16:42 UTC, the RIC received its first E2 Setup request.
2. The Agent received no Setup response and retried after three seconds.
3. At 23:16:45 UTC, the RIC aborted in add_reg_e2_node with:
   `Trying to add an already existing E2 Node`.
4. The Agent subsequently aborted in pend_event.
5. The node-discovery xApp waited until the Python subprocess timeout.
   Its one-off container remained running after the Compose client exited.

Relevant diagnostics:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  --profile tools ps -a
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  logs --no-color --timestamps --tail 100 ric emulator-2
```

Source inspection found that E2 Setup processing notified xApps before
returning the Setup response. Normal xApp shutdown notifications were
disabled, disconnected xApps were not removed from the connection map,
and node updates assumed contiguous xApp IDs starting at 7.

These findings motivated the fix. No stack trace proved the precise
blocking instruction in the failed run.

## 3. RIC source changes

| File under flexric/src/ric/iApp | Change |
| --- | --- |
| endpoint_iapp.c | Enable SCTP shutdown notifications |
| map_xapps_sockaddr.h | Declare association-based xApp lookup |
| map_xapps_sockaddr.c | Implement lookup and enable connection removal |
| e42_iapp.c | Identify normal shutdown by association, clean subscriptions and remove the connection |
| msg_handler_iapp.c | Iterate actual xApp records, use nonblocking sends on existing associations, and free the generated node array |

The node-update send path logs failures and does not retry them.
The generic duplicate-node registration assertion was not removed.

Inspect the source changes before committing:

```bash
git --no-pager diff --check
git --no-pager diff -- flexric/src/ric/iApp
```

## 4. Build the local RIC test image

```bash
sudo docker build \
  -f docker/flexric/Dockerfile \
  --target ric \
  --build-arg BUILD_JOBS=2 \
  -t oai-pi-flexric-ric:agent-recovery-test .
```

The first build failed because netinet/sctp.h preceded netinet/in.h.
After correcting the include order, the build completed successfully.

A local test can select the fixed image without changing the published
default:

```bash
sudo env FLEXRIC_RIC_IMAGE=oai-pi-flexric-ric:agent-recovery-test \
  docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  up -d --no-build --pull never --force-recreate \
  ric emulator emulator-2 emulator-3
```

During the recorded experiment, an equivalent temporary image override
file was used. The emulator and xApp images remained the published images.

## 5. Single-RIC recovery test

With the topology running:

```bash
python3 test/flexric/validate-agent-recovery.py \
  --scenario multi-agent \
  --output-dir /tmp/flexric-agent-recovery-fixed-single
```

The saved script performs these steps:

1. Run validate-topology.py for configuration, node discovery and KPM.
2. Record the running RIC container ID.
3. Stop emulator-2.
4. Poll xapp-nodes until RIC A advertises exactly nodes 1 and 3.
5. Recreate emulator-2 using --no-build, --no-deps and --pull always.
6. Poll until RIC A advertises nodes 1, 2 and 3 again.
7. Run fresh node-discovery and KPM checks.
8. Confirm the RIC is running with its original container ID.

Observed output included:

```text
PASS: agent2-absent, RIC A nodes=[1, 3]
PASS: agent2-returned, RIC A nodes=[1, 2, 3]
PASS: RIC A KPM nodes=[1, 2, 3]
PASS: RIC containers remained running with unchanged identities
PASS: Agent 2 recreation and fresh KPM subscriptions
```

The test leaves the topology running. Clean it before changing scenarios:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  --profile tools down --remove-orphans
```

## 6. Dual-RIC local test and control regression

Start both RICs with the local fixed image:

```bash
sudo env FLEXRIC_RIC_IMAGE=oai-pi-flexric-ric:agent-recovery-test \
  docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull never --force-recreate \
  ric ric-2 emulator emulator-2 emulator-3
```

Run recovery:

```bash
python3 test/flexric/validate-agent-recovery.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-agent-recovery-fixed-dual
```

Expected groups are RIC A nodes 1 and 2, and RIC B node 3. During Agent 2
absence, RIC A advertises only node 1. After recreation, its group returns
to 1 and 2. Fresh KPM checks cover both groups. Both RIC container IDs
must remain unchanged.

Check control routing after recovery:

```bash
python3 test/flexric/validate-topology.py \
  --scenario multi-ric \
  --checks control \
  --output-dir /tmp/flexric-agent-recovery-fixed-control
```

The control test verifies that RIC A rejects absent node 3 without sending
a control request, while RIC B sends to Agent 3 and receives an ACK.
Only the selected Agent receives the emulator handover request.

Both local recovery scenarios and the control regression passed.

## 7. Publish the fixed RIC image

```bash
sudo docker tag \
  oai-pi-flexric-ric:agent-recovery-test \
  limx59/flexric-ric:arm64-multi-agent
```

```bash
sudo docker push limx59/flexric-ric:arm64-multi-agent
```

The recorded push returned the RIC digest listed in section 1.

The multi-agent overlay sets ric to this tag. The multi-RIC overlay sets
ric-2 to the same tag. The base single-emulator deployment retains its
original arm64 image.

## 8. Validate the Docker Hub deployment

Start without the temporary local override, explicitly pulling images:

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
  up -d --no-build --pull always --force-recreate \
  ric ric-2 emulator emulator-2 emulator-3
```

```bash
python3 test/flexric/validate-agent-recovery.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-dockerhub-agent-recovery-dual
```

The published-image run passed baseline discovery and KPM, Agent removal,
rediscovery, fresh KPM subscriptions and unchanged RIC container IDs.

Inspect actual runtime image references:

```bash
sudo docker inspect \
  oai-pi-flexric-lab-ric-1 \
  oai-pi-flexric-lab-ric-2-1 \
  --format '{{.Name}} image={{.Config.Image}} id={{.Image}} running={{.State.Running}}'
```

```bash
sudo docker image inspect limx59/flexric-ric:arm64-multi-agent \
  --format 'ID={{.Id}} RepoDigests={{json .RepoDigests}}'
```

Both running RIC references and the published RepoDigest were verified in
the recorded experiment.

## 9. Save logs and inspect errors

Before removing containers:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  logs --no-color --timestamps \
  ric ric-2 emulator emulator-2 emulator-3 \
  > /tmp/flexric-agent-recovery-events.log
```

```bash
grep -iE \
  'assertion|segmentation fault|aborted|error sending|node update to xapp' \
  /tmp/flexric-agent-recovery-events.log
```

No output from grep means no matching lines; it is not proof that every
possible error is absent. The local dual-RIC inspection recorded 12 xApp
disconnections and no matching crash or send-error messages.

Evidence from the recorded runs:

- /tmp/flexric-agent-recovery-fixed-single
- /tmp/flexric-agent-recovery-fixed-dual
- /tmp/flexric-agent-recovery-fixed-control
- /tmp/flexric-agent-recovery-fixed-events.log
- /tmp/flexric-dockerhub-agent-recovery-dual/container-events.log

These are host-local evidence files, not files committed to Git.
The validator saves baseline and recovered check logs in subdirectories.

## 10. Cleanup

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  --profile tools down --remove-orphans
```

All five experiment containers were removed after the final validation.
The external bridge, published images and existing core deployment remain.

If terminal echo or newline formatting is disturbed:

```bash
stty sane echo opost onlcr
```

## Limits and failure handling

The recovery script requires an already running topology. Discovery polls
use a default 90-second deadline; individual Docker commands also have
timeouts. The script attempts to restart Agent 2 if failure occurs while
it is stopped.

A subprocess timeout may leave a one-off xApp container running. Preserve
its logs, inspect ps -a, then clean the experiment project before retrying.
Do not interpret a timeout as a successful recovery.

This experiment covers normal xApp shutdown and one Agent recreation per
run. It does not validate abrupt xApp failure, disconnect with active
subscriptions, lost node-update retries, arbitrary duplicate E2 Setup
handling, automatic restoration of old subscriptions, RIC failover,
cross-RIC state sharing, or real radio handover.
