# Experimental proactive RIC failback

Validated on ARM64 Raspberry Pi on 2026-10-11, Pacific time.
This completes the proactive failback subcase within the original
Node discovery / automatic RIC failover TODO scope.

## Validated behavior

RIC A initially serves nodes 1 and 2; RIC B serves node 3.

1. Inject SIGKILL into A.
2. Agents 1 and 2 switch to B without restarting.
3. Fresh backup KPM reports nodes 1, 2 and 3; subscription cleanup succeeds.
4. Restart A while B remains running.
5. Agents confirm three successful primary SCTP transport probes and
   proactively return to A without restarting.
6. Fresh KPM on A reports nodes 1 and 2; subscription cleanup succeeds.
7. Discovery and KPM confirm the original topology without Agent recreation.

Backup RIC and Agent 3 process identities remain unchanged.
The dedicated validator passed once, followed by three local-image
regression rounds and three published-image regression rounds.

## Implementation and boundaries

`apply-ric-failback.py` applies only to the copied `/src/flexric` source
during Docker builds. Repository FlexRIC source remains unchanged.

Enable with `RIC_FAILBACK_TEST=1`, together with `RIC_BACKUP_IP`.
The native Emulator event loop owns nonblocking SCTP transport probes.
Probe attempts are separated by at least five seconds; each pending
attempt has a two-second deadline checked by the event loop.
Three consecutive successes trigger primary endpoint selection and
an immediate E2 Setup request. Failed probes reset the confirmation count.

These probes confirm SCTP reachability, not E2 application health.
The validator separately checks E2 Setup, discovery and fresh KPM.
Primary restart is initiated by the validator; Agent return is automatic.

Existing xApp subscriptions do not migrate. Fresh subscriptions are used.
Blackhole-triggered proactive return, recovery flapping, active-subscription
failback, Proxy Agents, aperiodic subscriptions and production availability
are outside this demonstrated scope. Timing settings are experimental.

## Published images

Agent: `limx59/flexric-emulator:arm64-ric-failback`

Validated image-index digest:
`sha256:739bb2f55672061d6631c691d80bf21f863395c7e7d0039f36c6f974683c9c25`

RIC: `limx59/flexric-ric:arm64-ric-rejoin`

Tags are mutable. Runtime image IDs differ from image-index digests.

## Deployment

Run from the repository root. Use the existing external
`oai-pi-flexric-lab` network and multi-RIC prerequisites.

```bash
failback_compose() {
  sudo docker compose \
    -f deploy/oai-flexric/compose.emulator.yaml \
    -f deploy/oai-flexric/compose.multi-agent.yaml \
    -f deploy/oai-flexric/compose.multi-ric.yaml \
    -f deploy/oai-flexric/compose.ric-failover.yaml \
    -f deploy/oai-flexric/compose.ric-blackhole.yaml \
    -f deploy/oai-flexric/compose.ric-rejoin.yaml \
    -f deploy/oai-flexric/compose.ric-failback.yaml \
    "$@"
}
failback_compose pull ric ric-2 emulator emulator-2
```

For a stopped lab:

```bash
failback_compose up -d --no-build --pull never ric ric-2
failback_compose up -d --no-build --pull never --no-deps \
  emulator emulator-2 emulator-3
```

When replacing running RIC images, stop Agents first.
See [blackhole deployment guidance](README.ric-blackhole.md).

## Automated validation

These commands inject SIGKILL into A and restart it.
Do not run concurrently with other lab tests.

```bash
python3 test/flexric/validate-ric-failback.py \
  --output-dir /tmp/flexric-ric-failback-automated \
  </dev/null
```

```bash
python3 test/flexric/validate-ric-failback-regression.py \
  --output-dir /tmp/flexric-dockerhub-failback-regression \
  </dev/null
```

The regression verifies all three round summaries and archives evidence
under `~/Work/oai-test-evidence/`. Each round restores the baseline
without recreating Agents. This validates repeated SIGKILL/recovery
cycles within the same Agent processes.

Published-image evidence: `regression-3bbiti84`.

Archive:
`flexric-ric-failback-regression-20261011-184653-regression-3bbiti84.tar.gz`

## Cleanup

The validator removes its named temporary KPM containers and attempts
baseline restoration. Failed restoration is recorded in `summary.json`;
inspect the lab before retrying. Abrupt termination may bypass cleanup.

This validator does not install firewall rules or change host networking.

Using the shell function defined above:

```bash
failback_compose --profile tools down --remove-orphans
```

Verify no project containers remain:

```bash
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-flexric-lab \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

The external network, images and archived evidence are retained.
