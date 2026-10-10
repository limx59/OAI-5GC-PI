# Persistent KPM subscription recovery

## Purpose

Validated on an ARM64 Raspberry Pi on 2026-10-09, Pacific time.

Scenario: `ric-restart`. Gracefully restart RIC A while the persistent
xApp and Agent processes remain running. The patched SDK reconnects
and replays subscriptions. RIC B provides an independent control group.

The two RICs, three Agents and temporary xApps run in separate containers.
The host Python validator orchestrates Compose and checks evidence.

See [the RIC recovery guide](README.ric-recovery.md) for the preceding
fresh-subscription restart and explicit Agent migration tests.

## Published images

| Component | Image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Agent | limx59/flexric-emulator:arm64-kpm-recovery |
| xApp | limx59/flexric-xapp:arm64-kpm-recovery |

Validated image-index digests:

- Agent: sha256:7910d282d67af03f8eee64a2a4ca9e22d35fe10d5312574aa2b0c8f563b9601a
- xApp: sha256:2e66fe14e328a0fc9c1ec8acdaac5b6b38120474b1a6d0ae1675903527bcd7e7

Tags are mutable. Pull explicitly before testing.
Runtime image IDs and configured image names are recorded in summary.json.
Runtime image IDs differ from image-index digests.

## Preparation and deployment

Requirements: Python 3, Docker Compose, sudo, SCTP support, Docker Hub
access and the prepared external oai-pi-flexric-lab network.
Start with no previous experiment containers in this project.
No OAI UE or Open5GS core is required.

RIC A: 172.29.0.10, nodes 1 and 2.
RIC B: 172.29.0.11, node 3.
Agents: 172.29.0.20 through 172.29.0.22. PLMN: 505/01.

Run from the repository root. Define a shell helper for the four files:

```bash
cd ~/Work/oai-5gc-pi-review
recovery_compose() {
  sudo docker compose \
    -f deploy/oai-flexric/compose.emulator.yaml \
    -f deploy/oai-flexric/compose.multi-agent.yaml \
    -f deploy/oai-flexric/compose.multi-ric.yaml \
    -f deploy/oai-flexric/compose.kpm-recovery.yaml "$@"
}
```

Pull and start RICs before Agents:

```bash
recovery_compose --profile tools pull \
  ric ric-2 emulator emulator-2 emulator-3 xapp-kpm xapp-kpm-ric2
recovery_compose up -d --no-build --pull never ric ric-2
recovery_compose up -d --no-build --pull never --no-deps \
  emulator emulator-2 emulator-3
```

Validate the baseline:

```bash
python3 test/flexric/validate-topology.py \
  --scenario multi-ric --checks config nodes kpm \
  --emulator-image limx59/flexric-emulator:arm64-kpm-recovery \
  --xapp-image limx59/flexric-xapp:arm64-kpm-recovery \
  --output-dir /tmp/flexric-dockerhub-kpm-recovery-baseline </dev/null
```

## Automated test

```bash
python3 test/flexric/validate-kpm-recovery.py \
  --scenario ric-restart \
  --output-dir /tmp/flexric-dockerhub-kpm-recovery </dev/null
```

The validator creates two unique temporary xApps, checks baseline reports,
stops RIC A, observes RIC B for five seconds, starts RIC A and waits
up to 60 seconds for replay ACKs and resumed reports.

Pass criteria:

- Expected subscriptions and at least two baseline reports per node.
- RIC B reports during the outage and after RIC A restarts.
- Replay ACKs for requests 1 and 2, and resumed reports from both A nodes.
- Container IDs, image IDs and restart counts remain unchanged.
- Only RIC A's startup time changes.
- Normal cleanup returns two deletion responses for A and one for B.
- Both xApps exit zero; infrastructure remains running without assertions.

The validator creates /tmp/kpm-recovery-stop inside each xApp to end its
Python loop and execute subscription deletion. SIGINT is unsuitable:
the SDK signal handler performs an abrupt shutdown.
The xApp also has a 180-second maximum observation period.

Temporary xApps are removed after evidence capture. On failure the
validator attempts to start RIC A; inspect evidence and perform full
environment cleanup before retrying.

## Patch ownership

test/flexric/patches/apply-kpm-recovery.py changes only the dedicated
image build's /src/flexric copy. Repository FlexRIC source is unchanged.

Changes include saved-request ownership, xApp reconnect and replay,
replay-ACK handling, Agent association notifications, a duplicate
Setup-timer guard and level-triggered Agent epoll for single-message reads.

Patch anchors are checked before writing. FlexRIC upgrades that change
these anchors fail the build and require review. Upstream UNIT_TEST is OFF.

Optional rebuild:

```bash
recovery_compose --profile tools build xapp-kpm emulator
```

The independent native Compose regression passed both local tests:
xapp_subscription_cleanup and subscription_request_copy.
The latter checks deep ownership, optional fields and empty requests.
The previously published native regression image has not been updated
by these recovery-image uploads.

## Observed results and evidence

Local integration passed:

/tmp/flexric-kpm-recovery-level-triggered/run-oeeclocx

Published-image automated integration passed:

/tmp/flexric-dockerhub-kpm-recovery/run-zqj2wnsq

Both runs validated replay, resumed reports and normal cleanup.
Earlier unsuccessful attempts remain failure evidence.

Each run saves command logs, timestamped container logs, inspections
and summary.json. Keep raw evidence and archives outside Git.

```bash
mkdir -p "$HOME/Work/oai-test-evidence"
tar -czf "$HOME/Work/oai-test-evidence/flexric-dockerhub-kpm-recovery-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp flexric-dockerhub-kpm-recovery \
  flexric-dockerhub-kpm-recovery-baseline
```

Observed archive:

~/Work/oai-test-evidence/flexric-dockerhub-kpm-recovery-20261009-215817.tar.gz

## Cleanup

After the complete test, run in the same shell where recovery_compose
was defined:

```bash
recovery_compose --profile tools down --remove-orphans
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-flexric-lab \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

Both RICs and all three Agents were removed after this run.
The validator removed its temporary xApps. The final project check
returned only the table header. External networks and the existing
core deployment were retained.

## Limitations

Validated: one graceful same-address restart using emulator KPM,
subscription replay in the same xApp process and normal cleanup.

Repeated restarts, abrupt crashes, subscription changes during outages,
automatic cross-RIC failover, real OAI/RF recovery, counter accuracy
and Kubernetes deployment remain unvalidated.

Replay recreates RIC subscriptions; it does not preserve RIC-side state
or establish lossless delivery. Old Agent subscription state and
repeated-restart behavior require additional review.

## Detailed native patch rationale

See [the patch reference](patches/README.md) for affected FlexRIC source files, recovery changes, validation limits and upgrade guidance.
