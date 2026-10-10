# QoS monitoring with online Agent pause

Validated on an ARM64 Raspberry Pi on 2026-10-09, Pacific time.

## Scenario and scope

The `agent-pause` scenario pauses Agent 2 for eight seconds, detects
missing valid KPM measurements, resumes the Agent, and checks report
recovery and QoS alert rearming.

RIC A serves nodes 1 and 2. RIC B serves node 3.
Two RICs, three Agents and two temporary monitoring xApps run in separate
containers. Node 1 provides a same-RIC control; node 3 provides a
cross-RIC control.

This validates a short process pause with existing subscriptions.
Agent termination, recreation, long outages, automatic cross-RIC
failover and actual radio QoS enforcement remain unvalidated here.

See [QoS monitoring](README.qos-watch.md) and
[persistent KPM recovery](README.kpm-recovery.md) for preceding tests.

## Published images

| Component | Image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Agent | limx59/flexric-emulator:arm64-qos-fault |
| xApp | limx59/flexric-xapp:arm64-qos-fault |

Validated image-index digests:

- Agent: sha256:815b6612abb2fde69b6559807fd15156c0e3a252be1b30b3d1269738b1363b16
- xApp: sha256:6d36972bb2f1a78493193a74b14c6236e3e3870958445deca8884284c405acc6

Tags are mutable. Pull explicitly before testing.
The validator saves Docker inspection evidence, including runtime image
IDs and configured image names.

## Deployment

Requirements: Python 3, Docker Compose, sudo access, host SCTP support,
Docker Hub access and the existing external `oai-pi-flexric-lab` network.
Begin with no previous experiment containers in this Compose project.

Run from the repository root. Define a shell helper:

```bash
cd ~/Work/oai-5gc-pi-review
qos_compose() {
  sudo docker compose \
    -f deploy/oai-flexric/compose.emulator.yaml \
    -f deploy/oai-flexric/compose.multi-agent.yaml \
    -f deploy/oai-flexric/compose.multi-ric.yaml \
    -f deploy/oai-flexric/compose.kpm-recovery.yaml \
    -f deploy/oai-flexric/compose.qos-fault.yaml "$@"
}
```

Pull the published images and validate the merged configuration:

```bash
qos_compose --profile tools pull \
  ric ric-2 emulator emulator-2 emulator-3 xapp-kpm xapp-kpm-ric2
qos_compose --profile tools config --quiet
```

Start RICs before Agents:

```bash
qos_compose up -d --no-build --pull never ric ric-2
qos_compose up -d --no-build --pull never --no-deps \
  emulator emulator-2 emulator-3
```

Check the topology baseline:

```bash
python3 test/flexric/validate-topology.py \
  --scenario multi-ric \
  --checks config nodes kpm \
  --emulator-image limx59/flexric-emulator:arm64-qos-fault \
  --xapp-image limx59/flexric-xapp:arm64-qos-fault \
  --output-dir /tmp/flexric-dockerhub-qos-fault-baseline \
  </dev/null
```

Run the automated fault scenario:

```bash
python3 test/flexric/validate-qos-fault.py \
  --scenario agent-pause \
  --output-dir /tmp/flexric-dockerhub-qos-fault \
  </dev/null
```

## Monitoring and pass criteria

The test uses threshold 1000000000 and two consecutive low reports
to trigger deterministic test alerts. These are emulator-reported units,
not an operational SLA threshold.

A five-second timeout tracks each node and metric independently.
The watchdog runs even when no callback arrives. Monitoring begins
when a metric first supplies valid measurements; first-report absence
is not checked by the live xApp.

| Phase | Required behavior |
| --- | --- |
| Baseline | One initial alert for each node and DL/UL metric |
| Agent 2 paused | One STALE event per node 2 metric |
| Control nodes | Nodes 1 and 3 continue reporting without alert resets |
| Agent 2 resumed | One REPORT_RECOVERY per node 2 metric |
| Alert rearming | Node 2 alerts again after two consecutive low reports |
| Identity checks | All container IDs, startup times and restart counts unchanged |
| Cleanup | xApps exit 0; two deletion responses from A and one from B |
| Lab health | Both RICs and all Agents remain running |

REPORT_RECOVERY means valid measurements resumed. It does not mean
throughput crossed the QoS threshold.

The validator creates unique temporary xApp names and evidence directories.
It attempts to unpause Agent 2 on failure, saves logs and inspection
evidence, and removes its temporary xApps. A failed run may require
lab teardown before retrying. The validator leaves the lab deployed.

## Isolated build changes

Tracked FlexRIC source files are not modified.

- `test/xapp/qos_report_state.py`: per-metric silence state.
- `test/xapp/xapp_qos_fault_watch.py`: persistent QoS callback and watchdog.
- `test/flexric/test-qos-report-state.py`: deterministic state tests.
- `test/flexric/patches/apply-qos-fault.py`: Agent epoll EINTR handling.
- `docker/flexric/Dockerfile.qos-fault`: extends the KPM recovery xApp image.
- `docker/flexric/Dockerfile.qos-fault-agent`: builds the patched Agent.

The initial Agent crashed after unpause because epoll_wait returned
errno 4 (EINTR). The dedicated Agent build handles this by returning
to its event loop. Other epoll errors retain their existing checks.

The Agent Dockerfile first applies the existing KPM recovery patches,
then the QoS fault patch, only to `/src/flexric` inside the build.
Strict source anchors fail if upstream code changes unexpectedly.
Upstream UNIT_TEST remains OFF.

Local build and state regression:

```bash
python3 test/flexric/test-qos-report-state.py
python3 test/flexric/test-qos-node-state.py
qos_compose --profile tools build xapp-kpm emulator
```

## Observed results

All five report-state tests passed.
The fixed local-image automated run passed at
`/tmp/flexric-qos-fault-automated/run-usxwv6tj`.

The published-image automated run passed at
`/tmp/flexric-dockerhub-qos-fault/run-75odea_8`.
Baseline configuration, discovery and KPM checks also passed.
The lab was removed and the Compose project had no remaining containers.

## Evidence and cleanup

Archive outside the repository in the dedicated evidence directory:

```bash
mkdir -p ~/Work/oai-test-evidence
tar -czf "$HOME/Work/oai-test-evidence/flexric-dockerhub-qos-fault-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp \
  flexric-dockerhub-qos-fault \
  flexric-dockerhub-qos-fault-baseline
```

Remove experiment containers:

```bash
qos_compose --profile tools down --remove-orphans
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-flexric-lab \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

The external network and cached images remain available.
