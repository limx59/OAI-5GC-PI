# FlexRIC RIC restart and cross-RIC Agent migration

## Purpose and validated environment

Validated on an ARM64 Raspberry Pi on 2026-10-09, Pacific time.

| Scenario | Operation | Expected result |
| --- | --- | --- |
| ric-restart | Gracefully stop and start RIC A | Existing Agent processes reconnect to RIC A |
| ric-migration | Change Agent 2 configuration and recreate its container | Node 2 moves from RIC A to RIC B, then returns |

Both scenarios check node discovery, fresh KPM subscriptions, report
delivery and subscription deletion responses.

The two RICs, three emulator Agents and temporary xApps run in separate
containers and communicate over SCTP. The host-side Python validator
orchestrates Docker Compose and checks evidence.
The existing Open5GS, UERANSIM and ReDroid deployment is outside this test.

This extends the [Agent recreation experiment](README.agent-recovery.md).
No new FlexRIC source changes or upstream UNIT_TEST execution are required.

Requirements: Python 3, Docker Compose, sudo access, host SCTP support
and access to Docker Hub.

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

## Network and published images

| Service | Address | Initial node group |
| --- | --- | --- |
| ric | 172.29.0.10 | 1, 2 |
| ric-2 | 172.29.0.11 | 3 |
| emulator | 172.29.0.20 | Node 1 |
| emulator-2 | 172.29.0.21 | Node 2 |
| emulator-3 | 172.29.0.22 | Node 3 |

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Emulator | limx59/flexric-emulator:arm64-multi-agent |
| xApps | limx59/flexric-xapp:arm64-multi-agent |

Tags are mutable. The validator saves running container image IDs in its
identity snapshots; these are not registry manifest digests.

The validator explicitly selects the images above. Unset local image
overrides before deploying this environment:

```bash
unset FLEXRIC_RIC_IMAGE FLEXRIC_EMULATOR_IMAGE FLEXRIC_XAPP_IMAGE
```

Inspect the external lab bridge and address usage:

```bash
sudo docker network inspect oai-pi-flexric-lab \
  --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

If absent, check subnet conflicts and create the bridge once:

```bash
sudo docker network create --driver bridge \
  --subnet 172.29.0.0/24 oai-pi-flexric-lab
```

Stop other lab deployments occupying the listed addresses.

## Deploy the initial topology

Pull the published images:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  --profile tools pull \
  ric ric-2 emulator emulator-2 emulator-3 \
  xapp-nodes xapp-kpm xapp-nodes-ric2 xapp-kpm-ric2
```

Start both RICs:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull never ric ric-2
```

Start the three Agents:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull never --no-deps \
  emulator emulator-2 emulator-3
```

Verify the initial topology:

```bash
python3 test/flexric/validate-topology.py \
  --scenario multi-ric \
  --checks config nodes kpm \
  --output-dir /tmp/flexric-ric-recovery-baseline \
  </dev/null
```

Expected: RIC A nodes 1 and 2, RIC B node 3, and fresh KPM checks
passing for both groups.

## Run the reusable validator

### Graceful RIC restart

```bash
python3 test/flexric/validate-ric-recovery.py \
  --scenario ric-restart \
  --output-dir /tmp/flexric-dockerhub-ric-recovery \
  </dev/null
```

The validator:

1. Records identities and checks baseline discovery and KPM on both RICs.
2. Stops RIC A gracefully.
3. Requires both attached Agents to log communication loss and Setup retry.
4. Checks node discovery and fresh KPM on RIC B during the outage.
5. Starts RIC A and waits for nodes 1 and 2 to return.
6. Checks fresh KPM subscriptions on both RICs.
7. Requires all container IDs and restart counts to remain unchanged.
8. Requires Agent and RIC B startup times to remain unchanged, while
   RIC A startup time changes.

Expected final output:

```text
PASS: unchanged Agent and RIC B container identities and startup times
PASS: graceful RIC A restart recovery
```

### Explicit cross-RIC migration

```bash
python3 test/flexric/validate-ric-recovery.py \
  --scenario ric-migration \
  --output-dir /tmp/flexric-dockerhub-ric-migration \
  </dev/null
```

The migration overlay is deploy/oai-flexric/compose.ric-migration.yaml.
It mounts config/ric-recovery/e2agent-ric2.conf read-only into Agent 2,
changing its configured RIC address to 172.29.0.11 while retaining node ID 2.

The validator:

1. Checks baseline discovery and KPM: A={1,2}, B={3}.
2. Validates the migration configuration mount and target address.
3. Recreates only Agent 2 using the migration overlay and existing image.
4. Requires discovery and fresh KPM to show A={1}, B={2,3}.
5. Checks that only Agent 2 changed container ID and startup time;
   all running image IDs remain unchanged.
6. Recreates Agent 2 using the original three Compose files.
7. Requires discovery and fresh KPM to return to A={1,2}, B={3}.
8. Checks again that only Agent 2 was recreated.

Expected final output:

```text
PASS: migration, only Agent 2 recreated
PASS: restoration, only Agent 2 recreated
PASS: cross-RIC Agent migration and baseline restoration
```

This scenario performs an explicit configuration change and Agent
recreation. It does not implement automatic backup-RIC selection.

### Options and pass criteria

| Option | Description |
| --- | --- |
| --scenario | Required: ric-restart or ric-migration |
| --discovery-timeout | Discovery/retry polling deadline; default 90 seconds |
| --output-dir | Parent directory for a unique evidence directory |

Both scenarios require exact node groups, matching KPM subscription and
report node sets, one deletion response per expected node, and no detected
Assertion, Traceback or callback-error markers in checked xApp output.
Individual Docker commands have separate timeouts.

The validator requires an already running baseline topology.
It does not build or pull images. Run both scenarios before cleanup.
Each temporary xApp uses noninteractive Compose run and is explicitly
removed after execution.

## Observed results

| Scenario | Evidence directory | Result |
| --- | --- | --- |
| ric-restart | /tmp/flexric-dockerhub-ric-recovery/ric-ods4_qlq | PASS |
| ric-migration | /tmp/flexric-dockerhub-ric-migration/ric-2zhgzs96 | PASS |

The restart run observed both Agents detect disconnection and retry
Setup. RIC B discovery and fresh KPM passed during the outage.
After RIC A restarted, both node groups and fresh KPM checks passed.
Agent and RIC B identities and startup times remained unchanged.

The migration run passed baseline, migrated and restored discovery and
KPM checks. Node 2 moved to RIC B and returned to RIC A.
Only Agent 2 was recreated at each transition.

The preceding manual migration also verified A={1}, B={2,3}, KPM reports
and deletion responses on both RICs, followed by baseline restoration.

## Evidence and archiving

Each automated run saves command logs, container inspection logs,
identity JSON snapshots and summary.json under its unique evidence
directory. A PASS summary is written after successful scenario checks.

Archive both runs before cleanup:

```bash
tar -czf "$HOME/flexric-dockerhub-ric-recovery-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp flexric-dockerhub-ric-recovery
```

```bash
tar -czf "$HOME/flexric-dockerhub-ric-migration-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp flexric-dockerhub-ric-migration
```

Both archive commands completed successfully after the observed runs.
Keep raw logs and archives outside Git.

## Cleanup

After completing both scenarios and archiving evidence:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  --profile tools down
```

Check for remaining experiment containers:

```bash
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-flexric-lab \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

All five experiment containers were removed after the observed runs.
The project-filtered check displayed only the table header.
Cleanup targets this experiment project; retain the external bridge,
images and existing core, UERANSIM and ReDroid deployment.

## Limits and failure handling

The restart scenario covers graceful stop/start of the same RIC at the
same address. The migration scenario changes configuration and recreates
an Agent. Neither establishes abrupt-crash recovery, automatic cross-RIC
failover, shared RIC state, or automatic restoration of old subscriptions.

KPM checks use newly launched xApps and new subscriptions after each
transition. They do not demonstrate uninterrupted reporting or measure
recovery latency. Emulator measurements are synthetic; physical RF,
measurement accuracy and real UE handover are outside this test.

On an incomplete restart test, the validator attempts to start RIC A.
On an incomplete migration test, it attempts to recreate Agent 2 with
the baseline configuration. Failure-path restoration does not itself
verify recovered discovery and KPM; inspect the logs and rerun baseline
checks before retrying. Restoration can also fail if Docker is unavailable.

Polling deadlines are checked between discovery attempts; an individual
command can extend elapsed time beyond the polling deadline.
