# Experimental RIC network-blackhole validation

Validated on ARM64 Raspberry Pi on 2026-10-10, Pacific time.
This extends the original Node discovery / automatic RIC failover case.

## Results and boundaries

Manual validation, a single automated run, a three-run sequence and
the dedicated three-round regression script passed.

Each automated round verifies:

- Baseline discovery and KPM: RIC A nodes 1 and 2; RIC B node 3.
- SCTP packet drops between A and Agents 1 and 2.
- Agent failover to B with all five container processes unchanged.
- Fresh backup KPM for nodes 1, 2 and 3 and three subscription deletions.
- Removal of the test firewall table.
- Explicit recreation of Agents 1 and 2 to rejoin A.
- Restored discovery and KPM with both RICs and Agent 3 unchanged.

Agent recreation during restoration is separate from the failover interval.
Proactive automatic failback, existing xApp subscription migration,
active-subscription rejoin and production availability remain unvalidated.
Serialized RIC payload handling has not been throughput-tested.

The default published Agent image did not switch during an earlier
386-second observation. The experimental Agent uses opt-in per-socket
SCTP settings: RTO initial/minimum 1000 ms, maximum 2000 ms, association
maximum retransmissions 3. These are not production recommendations.

The original RIC aborted on duplicate node registration during restoration.
The experimental RIC handles association loss and repeated Setup, cleans
old node state and ignores notifications for unmapped associations.

## Prerequisites

Run commands from the repository root. Use the existing external network
`oai-pi-flexric-lab`, subnet 172.29.0.0/24, without address conflicts.

| Component | Address / initial nodes |
| --- | --- |
| RIC A | 172.29.0.10 / nodes 1 and 2 |
| RIC B | 172.29.0.11 / node 3 |
| Agent 1 | 172.29.0.20 |
| Agent 2 | 172.29.0.21 |

Required host tools: Docker Compose, Python 3, nsenter, nft and tar.
The validator needs sudo access and rejects host networking.
Run one lab test at a time.

Patches reside under `test/flexric/patches/` and apply only to the Docker
source copy `/src/flexric`. Repository FlexRIC source remains unchanged.
The experimental images are published on Docker Hub:

| Component | Published tag | Validated image-index digest |
| --- | --- | --- |
| Agent | `limx59/flexric-emulator:arm64-ric-blackhole` | `sha256:f5ce5e1c529385398f959a578a8d3a0cb3780db0ce076d0bfbd5210fd5a9408c` |
| RIC | `limx59/flexric-ric:arm64-ric-rejoin` | `sha256:34f3d07cd48c331fbd1aed6b2141ce8e9d49dc53c90689a8738070c715c542f7` |

Both published images passed the dedicated three-round regression on
2026-10-10, Pacific time, after an explicit Docker Hub pull.

Evidence run: `regression-6_v33b6y`.
Archive:
`flexric-ric-blackhole-regression-20261010-231745-regression-6_v33b6y.tar.gz`
under `~/Work/oai-test-evidence/`.

Tags are mutable. Image-index digests differ from runtime image IDs
recorded by Docker inspection.

## Build

```bash
sudo docker build \
  -f docker/flexric/Dockerfile.ric-blackhole-agent \
  --target emulator \
  -t limx59/flexric-emulator:arm64-ric-blackhole .
```

```bash
sudo docker build \
  -f docker/flexric/Dockerfile.ric-rejoin \
  --target ric \
  -t limx59/flexric-ric:arm64-ric-rejoin .
```

## Deploy

Define this helper in the current Bash session:

```bash
blackhole_compose() {
  sudo docker compose \
    -f deploy/oai-flexric/compose.emulator.yaml \
    -f deploy/oai-flexric/compose.multi-agent.yaml \
    -f deploy/oai-flexric/compose.multi-ric.yaml \
    -f deploy/oai-flexric/compose.ric-failover.yaml \
    -f deploy/oai-flexric/compose.ric-blackhole.yaml \
    -f deploy/oai-flexric/compose.ric-rejoin.yaml "$@"
}
```

Pull published images before deployment:

```bash
blackhole_compose pull ric ric-2 emulator emulator-2
```

The build commands above are optional for patch development and replace
the corresponding local tags. Pull again to deploy the published versions.

Stop existing Agents before replacing RICs:

```bash
blackhole_compose stop --timeout 15 emulator emulator-2 emulator-3
blackhole_compose up -d --no-build --pull never --no-deps \
  --force-recreate ric ric-2
blackhole_compose up -d --no-build --pull never --no-deps \
  --force-recreate emulator emulator-2 emulator-3
```

## Automated validation

Single round:

```bash
python3 test/flexric/validate-ric-blackhole.py \
  --output-dir /tmp/flexric-ric-blackhole-automated </dev/null
```

Three rounds, summary checks and automatic evidence archiving:

```bash
python3 test/flexric/validate-ric-blackhole-regression.py \
  --output-dir /tmp/flexric-ric-blackhole-regression </dev/null
```

The validator waits up to 120 seconds for switch and Setup confirmation.
Observation timing is not an exact failover latency measurement.

Each run saves logs, Docker inspection, fault evidence and `summary.json`.
The regression wrapper stops on failure and saves `regression-summary.json`.
Successful archives default to `~/Work/oai-test-evidence/`.

The dedicated regression passed as `regression-c8hibwh9`.
Archive:
`flexric-ric-blackhole-regression-20261010-225919-regression-c8hibwh9.tar.gz`.

Earlier three-round archive:
`flexric-ric-blackhole-three-rounds-20261010-225052.tar.gz`.

Evidence archives are local and are not included in Git.

## Cleanup

The validator creates a uniquely named nft table only inside RIC A's
network namespace, dropping SCTP traffic to/from Agents 1 and 2.
Host firewall rules, routes and sysctls are unchanged.

Normal completion removes the table and temporary xApps and restores
the baseline by recreating Agents 1 and 2. Exception cleanup attempts
the same actions and records errors. Abrupt termination, SIGKILL or
a changed RIC process can prevent automatic cleanup.

If interrupted, inspect `fault.json` and its `rollback_command`.
Before manual namespace operations, verify the saved RIC container
identity, PID and namespace and confirm isolation from the host.
Never blindly execute a rollback command with a stale PID.
Inspect evidence before retrying if restoration failed.

Remove the complete experimental lab:

```bash
blackhole_compose --profile tools down --remove-orphans
```

Verify no project containers remain:

```bash
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-flexric-lab \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

The external network and local images remain.
