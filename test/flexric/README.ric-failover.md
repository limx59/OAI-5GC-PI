# Experimental native Emulator RIC failover

Validated on an ARM64 Raspberry Pi on 2026-10-10, Pacific time.

## Scope and results

The dedicated Agent image automatically switches from primary RIC A
to backup RIC B after a detected connection loss and setup timeout.
This experiment uses native Emulator Agents and periodic subscriptions.

The automated validator passed:

- Initial discovery and KPM: RIC A nodes 1 and 2; RIC B node 3.
- Primary RIC SIGKILL while KPM subscriptions were active.
- Agents 1 and 2 switched without process restart.
- Backup RIC and Agent 3 processes remained unchanged.
- Fresh backup-RIC KPM subscriptions reported all three nodes.
- Fresh backup xApp exited normally with three subscription deletions.
- Initial topology was explicitly restored and KPM was rechecked.

Existing xApp subscriptions do not migrate. The old xApp can wait for
a deletion response from the unavailable primary and is explicitly
stopped by the validator. Restoration recreates Agents 1 and 2; this
is separate from the measured failover period.

Network blackhole detection, automatic failback, repeated failure cycles,
Proxy Agents, aperiodic subscriptions and production availability
remain unvalidated.

## Prerequisites and topology

Use the existing multi-RIC lab prerequisites and configuration.
The external network `oai-pi-flexric-lab` must exist with a compatible
172.29.0.0/24 subnet. Check for address conflicts before deployment.

| Component | Address / initial assignment |
| --- | --- |
| RIC A | 172.29.0.10; nodes 1 and 2 |
| RIC B | 172.29.0.11; node 3 |
| Agents 1 and 2 | RIC_BACKUP_IP=172.29.0.11 |

Run commands from the repository root. Python 3, Docker Compose, sudo
access and host SCTP support are required.

## Build and deploy

The failover image is a local test image; it has not been published.
Patches are stored in `test/flexric/patches/` and apply only to the
Docker build source copy `/src/flexric`. Repository FlexRIC source
must remain unchanged.

Patch order: KPM recovery, Agent epoll EINTR handling, RIC failover.
See [the patch documentation](patches/README.md).

```bash
sudo docker build \
  -f docker/flexric/Dockerfile.ric-failover-agent \
  --target emulator \
  -t oai-pi-flexric-emulator:ric-failover-test .
```

The base RIC, xApp and Agent 3 images must already be available locally.
Start the RICs first:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  -f deploy/oai-flexric/compose.ric-failover.yaml \
  up -d --no-build --pull never ric ric-2
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  -f deploy/oai-flexric/compose.ric-failover.yaml \
  up -d --no-build --pull never --no-deps \
  emulator emulator-2 emulator-3
```

## Automated validation

The validator requires the initial assignment A=[1,2], B=[3].
It injects SIGKILL into RIC A, creates temporary xApps, and restores
the initial assignment after testing. Run in a dedicated lab window.
Do not run concurrently with another topology-changing test.

```bash
python3 test/flexric/validate-ric-failover.py \
  --output-dir /tmp/flexric-ric-failover-automated </dev/null
```

Each run has a separate evidence directory containing logs, process
inspection records, baseline/restoration checks and `summary.json`.
Inspect cleanup errors if the validator fails. Successful restoration
leaves the lab running.

After a manual fault test, restart RIC A and explicitly recreate
Agents 1 and 2 before running this validator.

## Evidence archive

```bash
mkdir -p "$HOME/Work/oai-test-evidence"
tar -czf "$HOME/Work/oai-test-evidence/flexric-ric-failover-automated-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp flexric-ric-failover-automated
```

## Cleanup

After archiving evidence, remove this lab's containers, including
temporary xApp orphans:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  -f deploy/oai-flexric/compose.ric-failover.yaml \
  --profile tools down --remove-orphans
```

```bash
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-flexric-lab \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

The container list should be empty. Retain external networks, images
and archived evidence. Existing Open5GS, UERANSIM and redroid containers
belong to separate projects and are outside this cleanup scope.

## Upgrade requirements

Do not edit repository FlexRIC source to apply these patches.
Source-anchor checks reject incompatible upstream changes during the
Docker build. Adapt project patches and rerun the validator after
upgrading FlexRIC.
