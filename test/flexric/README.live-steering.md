# Live steering from controlled Emulator MAC load

Validated on an ARM64 Raspberry Pi on 2026-10-10, Pacific time.

## Scope

This experiment supplies controlled Emulator MAC reports over E2 and
evaluates steering recommendations online. It does not measure actual
radio utilization, send E2 control requests, or perform UE handover.

RIC A serves nodes 1 and 2. Their controlled DL loads feed the policy.
RIC B serves node 3, whose MAC reporting is checked by the baseline test.
The live policy does not aggregate load across RICs.

Two RICs, three Agents and temporary xApps run in separate containers.
The validators run on the host.

## Published images

| Component | Image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Agent | limx59/flexric-emulator:arm64-steering-load |
| xApp | limx59/flexric-xapp:arm64-steering-load |

Validated image-index digests:

- Agent: sha256:9d720dd023492e9107c0657c6ab93eb58627294775c14d1526f3ceda063d9b32
- xApp: sha256:1e8bd4d0045c87ca0f76118a387f20d0dea7fa642e9b6c1cb0ac5d0f64dc75ae

Tags are mutable. Pull explicitly before testing.
Docker inspection evidence records runtime image IDs, which differ
from image-index digests.

## Docker addresses and prerequisites

172.29.0.10 and 172.29.0.11 are Docker container addresses for RIC A and B,
not Raspberry Pi host addresses. Keep them when reproducing the same
single-host topology.

Requirements: Python 3, Docker Compose, sudo access, host SCTP support,
ARM64 image compatibility and an external Docker network named
oai-pi-flexric-lab with subnet 172.29.0.0/24.

Check for overlap with host, VPN and existing Docker networks.
If the subnet changes, update network settings, Compose addresses,
Agent and xApp configurations, and validator expectations together.
See [the RIC recovery guide](README.ric-recovery.md).

Start with no containers from earlier experiments in this Compose project.
No OAI UE or core network is required.

## Deployment

Run from the repository root. Default load files must contain 90, 20
and 40 for nodes 1, 2 and 3 respectively.

```bash
deploy="$PWD/deploy/oai-flexric"
compose=(sudo docker compose
  -f "$deploy/compose.emulator.yaml"
  -f "$deploy/compose.multi-agent.yaml"
  -f "$deploy/compose.multi-ric.yaml"
  -f "$deploy/compose.steering-load.yaml")
```

Pull the published images:

```bash
"${compose[@]}" --profile tools pull \
  ric ric-2 emulator emulator-2 emulator-3 xapp-kpm xapp-kpm-ric2
```

Start RICs before Agents:

```bash
"${compose[@]}" up -d --no-build --pull never ric ric-2
"${compose[@]}" up -d --no-build --pull never --no-deps \
  emulator emulator-2 emulator-3
```

## Automated tests

Use --use-image-code to run packaged Python code without host source mounts.
Without this option, validators mount their current local xApp dependencies
for development.

MAC baseline:

```bash
python3 test/flexric/validate-mac-load.py \
  --use-image-code \
  --output-dir /tmp/flexric-dockerhub-steering-mac-baseline </dev/null
```

Pass criteria:

- Only nodes 1 and 2 report through RIC A; only node 3 through RIC B.
- At least five valid reports per node.
- DL and UL loads are within 0.01 of 0.90, 0.20 and 0.40.
- xApps exit with status zero and receive all three delete responses.
- Both RICs and all Agents remain running and unpaused.

Live policy:

```bash
python3 test/flexric/validate-live-steering.py \
  --use-image-code \
  --output-dir /tmp/flexric-dockerhub-live-steering </dev/null
```

The validator sets 90%/20%, checks a forward recommendation and cooldown,
sets 50%/50% and checks balanced reports, then sets 20%/90% and checks
a reverse recommendation. Recommendations must respect the 30-second
cooldown. The reverse phase must include pending confirmation.
All results must have executed=false.

It checks unchanged container IDs, startup times, PIDs and restart counts
for the xApp and lab processes, normal subscription deletion and exit.
It restores the original load-file contents and removes its temporary xApp.
Do not run these validators concurrently or edit load files during testing.

## Controlled MAC model and isolated patches

The model assumes 106 PRBs per 500-microsecond slot for both DL and UL.
This is a test capacity, not measured radio capacity.

[apply-steering-load.py](patches/apply-steering-load.py) changes only
examples/emulator/agent/sm_mac.c in the Docker build's copied /src/flexric
tree. It replaces random MAC generation with
[steering_mac_report.h](native/steering_mac_report.h).

[steering_mac_load.h](native/steering_mac_load.h) reads configured load
percentages and accumulates PRBs using monotonic elapsed time.
The report contains one synthetic UE with RNTI 1.
The timestamp is monotonic microseconds in this dedicated implementation.

128-bit intermediate arithmetic supports long idle intervals.
The uint32 PRB wire counter wraps; the collector uses modular differences.
A sampling gap spanning a full counter cycle cannot be reconstructed from
these counters. Load changes apply the current percentage to the interval
since the preceding generated report; transition intervals are synthetic.

The xApp computes load from counter differences and elapsed report time.
The policy uses DL load, requires fresh reports from both nodes and
new timestamps since its previous evaluation, and evaluates at most
once per second. Stale input suppresses evaluation; it does not trigger
a migration or a separate stale notification.

The Agent image also includes the preceding KPM recovery and epoll EINTR
patches. Tracked FlexRIC source remains unchanged; upstream UNIT_TEST is OFF.
See [the patch guide](patches/README.md).

## Building and native verification

```bash
sudo docker build -f docker/flexric/Dockerfile.steering-load-agent \
  --target emulator -t oai-pi-flexric-emulator:steering-load-test .
sudo docker build -f docker/flexric/Dockerfile.steering-load-xapp \
  --target xapp -t oai-pi-flexric-xapp:steering-load-test .
```

Native tests cover full capacity, changing load, fractional accumulation,
zero elapsed time, a five-minute idle interval and uint32 counter wrap:

```bash
binary=$(mktemp /tmp/steering-mac-test.XXXXXX)
cc -std=gnu11 -Wall -Wextra -Werror \
  test/flexric/native/tst-steering-mac-load.c -o "$binary"
"$binary"
rm "$binary"
```

## Evidence and cleanup

Each validator creates a unique run directory with logs and summary.json.
Do not place archives directly in the home directory.

```bash
mkdir -p "$HOME/Work/oai-test-evidence"
tar -czf "$HOME/Work/oai-test-evidence/flexric-live-steering-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp flexric-dockerhub-steering-mac-baseline \
  flexric-dockerhub-live-steering
```

```bash
"${compose[@]}" --profile tools down --remove-orphans
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-flexric-lab \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

Actual multicell radio load, cross-RIC policy aggregation, UE handover,
closed-loop control and performance improvements remain unvalidated.
