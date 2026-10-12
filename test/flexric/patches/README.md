# FlexRIC isolated build patches

## Purpose and application boundary

These patches address issues encountered in persistent KPM recovery and
online QoS Agent pause tests on an ARM64 Raspberry Pi.

Patch scripts are maintained in this project's test/flexric/patches.
They modify only the copied /src/flexric tree during dedicated Docker
image builds. The repository's tracked flexric/src files remain unchanged.
The resulting images contain modified FlexRIC binaries.

These are project-maintained patches, not claims of upstream acceptance.
Upstream UNIT_TEST remains OFF.

## Persistent KPM recovery: apply-kpm-recovery.py

Source paths below are relative to the FlexRIC source root.

| Source file | Problem addressed | Patch behavior |
| --- | --- | --- |
| src/xApp/act_proc.h | Active procedures did not retain an independently owned request for replay | Adds saved_subscription, needs_replay and replay_ack_pending state and a save API |
| src/xApp/act_proc.c | Replaying a request requires its allocated fields to remain valid after the original request is released | Saves a deep copy; releases saved requests when procedures are removed or the registry is freed |
| src/xApp/subscription_request_copy.h (added during build) | A shallow copy would share event-trigger and optional action allocations | Copies event trigger, action definitions and subsequent-action fields independently; provides matching release logic |
| src/xApp/endpoint_xapp.h and src/xApp/endpoint_xapp.c | Returning only payload bytes did not expose SCTP shutdown notifications to the xApp event loop | Subscribes to shutdown events and returns the complete sctp_msg_t |
| src/xApp/e42_xapp.c | Existing xApp subscriptions were not replayed after graceful RIC restart | Detects shutdown, clears cached nodes, marks subscriptions for replay, restarts Setup and replays saved requests after the matching nodes register |
| src/xApp/msg_handler_xapp.c | Replay responses must not wake a synchronous UI wait for a different operation; registering pending state after transmission risks an early-response race | Distinguishes replay ACKs from normal responses; registers pending state before sending in the patched request paths |
| src/agent/endpoint_agent.c | Shutdown notification alone was insufficient for the observed association-loss behavior | Enables SCTP association notifications |
| src/agent/not_handler_agent.c | Association notifications require state filtering; repeated loss notifications can schedule duplicate Setup timers | Handles selected loss/restart states and shutdown; ignores other notifications and avoids adding another pending Setup timer |
| src/lib/ep/e2ap_ep.c | Copying only sac_state discarded other association-notification fields | Copies the complete sctp_assoc_change structure |
| src/agent/asio_agent.c | Edge-triggered epoll combined with one-message SCTP reads could leave queued messages unread | Uses level-triggered EPOLLIN so unread messages remain ready for subsequent iterations |

The copy helper originates from
[subscription_request_copy.h](../native/subscription_request_copy.h).
It is copied into the container source tree with adjusted include paths.

### Observed failure and validated behavior

Before recovery support, reports did not resume for the persistent xApp.
Its later subscription deletion encountered missing RIC request mappings
and a synchronous response timeout.

During patch development, a replay request reached an Agent only around
the RIC pending-event timeout. The Agent's edge-triggered, single-message
read behavior was identified as a contributing issue. Level-triggered
readiness was added; the subsequent complete recovery test passed.

Validated behavior includes one graceful same-address RIC A restart:
the existing xApp reconnects, replays requests, receives replay ACKs,
resumes KPM reports and deletes subscriptions normally.
RIC B continues reporting. Agent and xApp container identities and
startup times remain unchanged.

This restores reporting through subscription replay. It does not preserve
the restarted RIC's in-memory subscription objects.

Build integration:
[docker/flexric/Dockerfile.kpm-recovery](../../../docker/flexric/Dockerfile.kpm-recovery).

Test guide:
[Persistent KPM recovery](../README.kpm-recovery.md).

## Agent pause recovery: apply-qos-fault.py

| Source file | Observed problem | Patch behavior |
| --- | --- | --- |
| src/agent/asio_agent.c, event_asio_agent() | After docker unpause, epoll_wait returned errno 4 (EINTR), and the existing error path asserted | Returns the existing no-event value -1 for EINTR, allowing the Agent loop to continue; other errors retain their original checks |

The initial pause test produced this sequence:

1. Agent 2 resumed from pause and asserted after epoll_wait was interrupted.
2. Node 2 reports did not recover.
3. Later subscription deletion caused RIC A to assert because the node
   mapping was absent.
4. xApp A timed out waiting for the deletion response.

The QoS patch addresses the first failure. It does not directly modify
RIC node-map assertions or xApp timeout handling.

The dedicated Agent build applies apply-kpm-recovery.py first, then
apply-qos-fault.py. The QoS xApp image extends the published KPM recovery
xApp image and adds project Python monitoring code.

Build integration:
[Agent Dockerfile](../../../docker/flexric/Dockerfile.qos-fault-agent)
and [xApp Dockerfile](../../../docker/flexric/Dockerfile.qos-fault).

Test guide:
[QoS online Agent pause](../README.qos-fault.md).

## Test code versus native patches

The following project Python code adds monitoring and orchestration,
rather than modifying native FlexRIC behavior:

- test/xapp/qos_report_state.py tracks per-node, per-metric report silence.
- test/xapp/xapp_qos_fault_watch.py runs the watchdog, resets affected QoS
  counters after timeout and records report recovery.
- test/flexric/validate-kpm-recovery.py orchestrates the RIC restart case.
- test/flexric/validate-qos-fault.py orchestrates the Agent pause case.

QoS report monitoring begins after the first valid measurement for a
metric. REPORT_RECOVERY means measurements resumed, not that throughput
crossed the QoS threshold.

## Validation and limitations

Validated on 2026-10-09, Pacific time:

| Validation | Result |
| --- | --- |
| Subscription request independent ownership and release regression | Passed |
| Published-image persistent KPM recovery with normal deletion | Passed |
| Five deterministic report-silence state tests | Passed |
| Three existing QoS node-state tests | Passed |
| Published-image eight-second Agent 2 pause and resume | Passed |
| QoS control nodes, alert rearming, unchanged processes and normal deletion | Passed |

The tests do not establish support for abrupt RIC crashes, arbitrary
notification sequences, repeated RIC restarts, long Agent pauses,
Agent termination/recreation, automatic cross-RIC failover or real-radio
QoS enforcement.

## FlexRIC upgrades

Both scripts require the target path to resolve to /src/flexric and
each replacement anchor to occur exactly once.

The KPM script prepares and checks all replacements before writing its
source changes. The QoS script checks its single replacement before writing.

When an upstream upgrade changes an anchor, the build fails instead of
silently applying a patch at an uncertain location. Review the new source,
determine whether upstream already fixes the issue, and update or remove
the corresponding project patch.

After changing the source version or patches, rebuild and rerun the
relevant native regressions, topology baseline and integration tests.
A previous image's passing result does not validate an upgraded build.

## Controlled Emulator MAC load: apply-steering-load.py

This is a dedicated test-data adaptation, not a correction to actual
radio measurement semantics.

| Source file or helper | Problem or test requirement | Change |
| --- | --- | --- |
| examples/emulator/agent/sm_mac.c | Default random MAC reports cannot supply known normalized load for deterministic steering tests | Replaces fill_mac_ind_data with steering_fill_mac_report in the copied Docker build source |
| test/flexric/native/steering_mac_report.h | The test needs a stable UE and counters based on elapsed time | Generates one synthetic UE, monotonic timestamps and controlled DL/UL PRB counters |
| test/flexric/native/steering_mac_load.h | The original project helper aborted when repeated subscriptions were separated by more than 60 seconds | Uses 128-bit intermediate arithmetic without the 60-second assertion; preserves fractional increments and wraps the uint32 counter |
| test/xapp/xapp_mac_load.py | Wire counters wrap and repeated reports must be converted to normalized load | Uses modular counter differences and the configured test capacity |

The assumed capacity is 106 PRBs per 500-microsecond slot for both DL
and UL. It is synthetic and is not measured radio capacity.
A full counter cycle between samples cannot be recovered from the wire
counter. A load-file update applies its current percentage to the
interval since the previous generated report.

The patch script modifies only /src/flexric inside the dedicated Agent
image build. Tracked FlexRIC source remains unchanged. The image also
applies the preceding KPM recovery and Agent epoll EINTR patches.

Native checks cover capacity, changing load, fractional accumulation,
zero elapsed time, a five-minute idle interval and uint32 counter wrap.
Automated published-image checks cover three-node MAC load, forward and
reverse steering recommendations, balanced-load suppression, cooldown,
unchanged processes and subscription deletion.

See [the live steering guide](../README.live-steering.md) for reproduction
and validation boundaries.

## Experimental native Agent RIC failover: apply-ric-failover.py

This patch implements an experimental primary/backup RIC selection path
for native Emulator Agents with periodic subscriptions.

The dedicated Dockerfile is
`docker/flexric/Dockerfile.ric-failover-agent`.
It copies the patch scripts into the build container and applies them
before compilation, in this order:

1. `apply-kpm-recovery.py`
2. `apply-qos-fault.py`
3. `apply-ric-failover.py`

Patches modify only the copied source at `/src/flexric` inside the Docker
build. Do not modify the repository's `flexric/` source to apply these
changes. Exact source-anchor checks stop the build if an upstream update
changes the expected code. Adapt the patches and repeat validation after
upgrading FlexRIC.

Set `RIC_BACKUP_IP` to the backup RIC IPv4 address. On a detected
disconnect, the Agent clears its old periodic subscriptions. A setup
timeout selects the alternate RIC and replaces the SCTP endpoint.
Further setup timeouts alternate the configured endpoints.

Subscription cleanup executes independently of C assertions.
The experiment does not support Proxy Agents or aperiodic subscriptions.

Validated on the ARM64 Raspberry Pi on 2026-10-10, Pacific time:

- Primary RIC SIGKILL with active KPM subscriptions.
- Agents 1 and 2 connected to the backup RIC without restarting.
- Backup RIC and Agent 3 processes remained unchanged.
- Fresh backup-RIC KPM subscriptions reported nodes 1, 2 and 3.
- The fresh xApp exited normally with three subscription delete responses.
- The rebuilt image passed after removing the assertion-dependent
  cleanup call.

Existing xApp subscriptions do not migrate to the backup RIC.
The old xApp can wait for a deletion response from the unavailable
primary RIC and required manual termination in this experiment.
Network blackhole detection, automatic failback, repeated failure cycles
and production availability remain unvalidated.

The Compose overlay is `deploy/oai-flexric/compose.ric-failover.yaml`.
It enables the dedicated image and backup address for Agents 1 and 2.

## Experimental SCTP blackhole and RIC rejoin recovery

Both patches apply only to `/src/flexric` inside dedicated Docker builds.
Repository FlexRIC source must remain unchanged.

- `apply-ric-blackhole.py`: opt-in Agent socket settings enabled by
  `RIC_BLACKHOLE_TEST=1`; SCTP RTO initial/minimum 1000 ms, maximum
  2000 ms, association maximum retransmissions 3. These are experimental
  per-socket settings, not host sysctl changes or production recommendations.
- `apply-ric-rejoin.py`: subscribes the RIC to association events; removes
  old socket mappings, connected-node entries and iApp registrations;
  ignores notifications for unmapped associations; clears an existing
  node before repeated Setup; serializes E2 payload handling and disconnect
  cleanup with a dedicated mutex. Payload serialization changes concurrency
  and has not been validated for production throughput.

`Dockerfile.ric-blackhole-agent` applies KPM recovery, QoS fault handling,
Agent failover, then the blackhole socket patch.
`Dockerfile.ric-rejoin` applies the same first three patches, then RIC rejoin
recovery. Both Dockerfiles are under `docker/flexric/`.

The default published Agent image did not switch during the earlier
386-second observation. Tuned Agents switched in subsequent experiments.
The original RIC aborted on duplicate node registration during restoration;
the rejoin image passed explicit Agent recreation without restarting RICs.

Manual validation, one automated run and both three-round sequences passed
on 2026-10-10, Pacific time. The dedicated regression script validates
summaries and archives evidence automatically. Agent processes remain
unchanged during failover; Agents 1 and 2 are recreated for restoration.
RIC processes remain unchanged through restoration.

These results do not establish proactive automatic failback, existing
xApp subscription migration, active-subscription rejoin, or production
availability. After upgrading FlexRIC, review source anchors, rebuild and
repeat validation. See [the blackhole guide](../README.ric-blackhole.md)
for deployment and cleanup.

## Experimental proactive RIC failback

`apply-ric-failback.py` adds opt-in native Emulator proactive return
to the primary RIC. Apply it after the KPM recovery, QoS fault,
RIC failover and SCTP blackhole patches using
`docker/flexric/Dockerfile.ric-failback-agent`.

Set `RIC_FAILBACK_TEST=1`. Nonblocking SCTP transport probes require
three consecutive successes before requesting E2 Setup on the primary.
Use the rejoin-patched RIC, which handles unmapped probe associations.

Repository FlexRIC source remains unchanged. Only `/src/flexric`
inside the Docker build is accepted by the patch script.

Manual, automated and three-round local and published-image validation
passed. Fresh subscriptions are used; existing subscriptions do not migrate.
SCTP transport readiness does not establish E2 application health.

See [failback validation and Cleanup](../README.ric-failback.md).

## Experimental OAI SDK context and N2 handover build

`prepare-oai-ue-context.py` prepares only `/src/flexric` copied from the
OAI embedded SDK inside dedicated Docker builds. It replaces the examples
build entry with the query target and required NR RRC ASN.1 library.
The dedicated RIC Dockerfile additionally includes the RIC build target.

The regular standalone SDK's neighbour-table decoder is unimplemented.
Both dedicated RIC and xApp use the matching OAI SDK, its INI configuration
and SQLite database. Repository SDK sources remain unchanged.
The gNB Dockerfile installs the existing RC plugin without OAI source patches.

See [N2 handover validation and Cleanup](../README.oai-n2-handover.md).
