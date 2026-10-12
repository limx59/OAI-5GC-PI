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
| xApps | sha256:fa5e6e52d37850726d7b9465d0bbbfb4ad911a29ece328d2101cec2ee6a1ca96 |

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

## Multi-node QoS monitoring

See [the QoS experiment guide](README.qos-watch.md) for the multi-node state fix, regression tests, Docker Hub validation and cleanup.

The xApp digest above reflects the latest Python multi-source steering upload. Earlier topology and CSV tests used the previous xApp digest documented in that guide.

## Multi-node MAC/RLC/PDCP reporting

See [the radio statistics guide](README.radio-stats.md) for Docker Hub deployment, reusable validation, observed records and cleanup.

## Multi-node slice control

See [the slice-control guide](README.slice-control.md) for target selection, Docker Hub tests, control reception checks and cleanup. The guide also records the preceding QoS image digest.

## Python steering with multiple source nodes

See [the steering-control guide](README.steering-control.md) for mapping validation, Docker Hub tests, target reception and cleanup.

## OAI UE traffic KPM CSV recording

See [the OAI KPM recording guide](README.oai-kpm-recording.md) for
RFSim UE uplink/downlink traffic, CSV validation, published images,
observed results and cleanup.

## OAI UE traffic QoS monitoring

See [the OAI QoS guide](README.oai-qos-watch.md) for four
uplink/downlink alert cases, published images, evidence and cleanup.

## OAI KPM subscription cleanup regression

See [the OAI KPM subscription cleanup guide](README.oai-kpm-subscription-cleanup.md)
for environment preparation, published recorder images, reusable regression
commands, pass criteria, observed results, evidence archiving and cleanup.

Three uplink/downlink rounds passed with the published recorder on an
ARM64 Raspberry Pi on 2026-10-08, using the existing local radio-statistics
gNB image. Validation covers RFSim traffic, KPM CSV recording and normal
subscription cleanup; measurement accuracy and physical RF remain
unvalidated.

The same guide includes an independent Docker Compose source-level
regression for early ACK handling and distinct pending-request lookup
and removal. It passed on 2026-10-09 without enabling the upstream
UNIT_TEST suite. The updated published recorder includes the lookup fix
and passed a further three-round OAI KPM cleanup regression on 2026-10-09.

## OAI UE traffic MAC/RLC/PDCP reporting

See [the OAI radio statistics guide](README.oai-radio-stats.md) for
independent-container communication, Docker Hub images, Compose deployment,
uplink/downlink validation, observed results, evidence archiving and cleanup.

Both directions passed with the published radio-statistics gNB and updated
xApp on 2026-10-09. Validation covers report delivery, nonempty record lists
and subscription cleanup; individual counter accuracy and physical RF
remain unvalidated.

## RIC restart and cross-RIC Agent migration

See [the RIC recovery guide](README.ric-recovery.md) for published images,
independent-container deployment, reusable ric-restart and ric-migration
scenarios, pass criteria, observed results, evidence archiving and cleanup.

Both scenarios passed on an ARM64 Raspberry Pi on 2026-10-09.
Validation covers graceful same-address RIC restart, explicit Agent
migration between RICs, fresh KPM subscriptions and baseline restoration.
Automatic cross-RIC failover and restoration of old subscriptions remain
unvalidated.

## Persistent KPM subscription recovery

See [the persistent KPM recovery guide](README.kpm-recovery.md) for
Docker Hub images, independent-container deployment, the automated
ric-restart scenario, build-time patches, evidence archiving and cleanup.

The published-image test passed on an ARM64 Raspberry Pi on 2026-10-09:
the same xApp processes resumed reports after graceful RIC A restart,
RIC B continued reporting, and normal subscription deletion completed.
Repeated restarts, abrupt crashes and automatic cross-RIC failover remain
unvalidated.

## QoS monitoring with online Agent pause

See [the QoS fault guide](README.qos-fault.md) for published images,
deployment, the automated agent-pause scenario, isolated build patches,
pass criteria, evidence archiving and cleanup.

The published-image test passed on an ARM64 Raspberry Pi on 2026-10-09:
Agent 2 report silence was detected, valid reports resumed after unpause,
QoS alerts rearmed independently, and subscription cleanup completed.
Nodes 1 and 3 continued reporting; container identities and startup
times remained unchanged. Agent termination, recreation and long outages
remain unvalidated by this scenario.

## Live steering from controlled Emulator MAC load

See [the live steering guide](README.live-steering.md) for published
ARM64 images, deployment, automated MAC baseline and online policy tests,
controlled load generation, evidence archiving and cleanup.

The published-image tests passed on 2026-10-10: nodes 1, 2 and 3 reported
90%, 20% and 40% controlled MAC load; the online policy produced forward
and reverse recommendations, suppressed recommendations at balanced load,
respected cooldown and completed normal subscription cleanup.

This validates controlled Emulator reports and recommendations.
Actual multicell radio load, cross-RIC policy aggregation and closed-loop
UE handover remain unvalidated.

## Experimental OAI dual-cell RFsim

See [the dual-cell RFsim experiment guide](README.oai-multi-cell.md) for
deployment prerequisites, reproduction, failure evidence and cleanup.

Concurrent two-UE tests did not pass. The configurations remain experimental;
simultaneous two-UE traffic and measured multi-cell load remain unvalidated.

## Automatic RIC failover

See [the automatic RIC failover guide](README.ric-failover.md) for
dedicated patch builds, automated tests, regression results, Docker Hub
validation, validation limits and cleanup.

Validation includes fault-driven RIC failover and bidirectional A -> B -> A
reconnection within unchanged Agent processes in the stated experiment scope.

## Experimental RIC network blackhole

See [the RIC blackhole experiment guide](README.ric-blackhole.md) for
dedicated images, namespace-isolated SCTP packet drops, automated validation,
three-round regression tests, Docker Hub validation and cleanup.

Validation uses opt-in Agent socket settings and the RIC rejoin patch.
Agents fail over without restarting; restoration explicitly recreates
Agents 1 and 2 without restarting the RICs.

## Experimental proactive RIC failback

See [the proactive RIC failback guide](README.ric-failback.md) for
dedicated patch builds, automated validation, three-round regression tests,
Docker Hub validation, validation limits and cleanup.

After primary recovery, Agents proactively return while the backup RIC
remains running. Agent and backup RIC processes remain unchanged.
Transport probes do not establish E2 application health, and existing
xApp subscriptions do not migrate.

## OAI E2 RC-triggered N2 handover

See [the N2 handover experiment guide](README.oai-n2-handover.md) for
matched OAI SDK images, dedicated container CPU allocation, automated
validation, three-round regression tests, Docker Hub validation and cleanup.

Validation covers forward RFsim UE handover, target RRC completion and
NGAP Handover Notify, PDU session establishment, unchanged UE IP,
post-handover connectivity and unchanged container processes.
Load-driven closed-loop policy, reverse handover and interruption-time
validation remain pending.

## Test TODO and validation status

Updated after the Raspberry Pi experiments on 2026-10-11.
This table retains the original ten test cases. Follow-up work stays
within those cases rather than creating additional test cases.

“Completed” applies only to the scope stated below. Emulator-generated
load, RFsim protocol-stack statistics and physical RF measurements are
different validation scopes.

| Test case | Completed | Remaining |
| --- | --- | --- |
| Node discovery | ✅ Multiple Agents and RICs; discovery after Agent recreation; graceful RIC restart recovery; explicit cross-RIC attachment; automatic RIC failover in the dedicated patched Emulator image; three consecutive SIGKILL regression runs; published-image validation; manual and automated A -> B -> A failover with Agent 1 and 2 processes unchanged throughout; network blackhole failover with opt-in SCTP socket settings and the experimental RIC rejoin patch; dedicated three-round regression script passed with local and published Docker Hub images, including rule removal and explicit Agent rejoin without RIC restart; fresh KPM subscriptions, cleanup and baseline restoration; proactive automatic failback after primary recovery while backup remains running; dedicated three-round regression passed for local and published images, without Agent recreation between rounds | — |
| KPM monitoring | ✅ Multiple topologies; OAI UE traffic; new subscription recovery; existing subscription recovery and normal cleanup in the validated restart scenarios | — |
| KPM CSV recording | ✅ Multiple Agents and RICs; OAI UE uplink/downlink recording | — |
| QoS monitoring | ✅ Multi-topology alerts; independent per-node state; policy regression; OAI UE traffic; live Agent pause and recovery | — |
| MAC / RLC / PDCP statistics | ✅ Non-empty reports and subscription cleanup across multiple Agents and RICs; non-empty OAI records | — |
| Traffic steering policy | ✅ Synthetic policy tests; live controlled Emulator MAC load; forward/reverse recommendations; balanced-load suppression; cooldown; automated tests | ☐ **Live multi-cell load: concurrent dual-cell RFsim tests did not pass; experimental configurations and failure evidence saved; deferred** |
| 🔴 **Traffic steering control** | ✅ Directed multi-Agent control; multi-RIC ACKs; Python source-node mapping; real E2 RC-triggered forward N2 RFsim UE handover; target RRC completion and NGAP Notify, PDU session, unchanged IP and post-handover traffic feedback; dedicated CPU allocation; three local and three published-image regression rounds | ☐ Load-driven closed-loop policy; reverse handover and interruption-time validation |
| Multi-Agent slicing control | ✅ Slicing policy; directed single/multi-Agent and multi-RIC control with ACKs | ☐ Actual PRB allocation execution; prioritize simulation |
| Energy-saving control | ✅ Policy and state-feedback simulation | ☐ Physical device control and power measurements; deferred due to unavailable hardware |
| Combined regression | ✅ Reusable Emulator regression tests | ☐ Physical RF validation; deferred due to unavailable SDR hardware |

### Current laboratory limits and RFsim result

The current Raspberry Pi has four Cortex-A76 CPU cores and about 8 GiB
RAM. No SDR is available. Continue software simulation where supported;
skip physical-equipment-only execution in this laboratory and retain
those items above for future contributors.

Two RFsim gNBs completed NG, F1 and E2 setup. Each gNB/UE pair separately
established a session and reached the UPF during the 106 PRB experiments.
That does not establish simultaneous dual-cell operation.

Concurrent dual-cell attempts failed at both 106 PRB and 24 PRB.
The UE RRC queues accumulated messages and a UE aborted at
fill_msg3_pdu_from_rlc() with “no data for Msg3/MsgA_PUSCH”.
Reducing each UE to one DL actor and one UL actor did not resolve the
failure. In that run, UE1 aborted; UE2 received Registration Accept but
had no TUN interface at inspection.

Resource contention is a working hypothesis, not an isolated root
cause. Simultaneous two-UE traffic and measured multi-cell load
have not passed. A separate one-UE/two-gNB N2 mobility experiment passed
forward handover with state and post-handover data-plane feedback under
dedicated container CPU allocation. Load-driven closed-loop policy remains
unvalidated. The multi-cell Compose overlay
and configurations are experimental and must not be treated as a
validated deployment.

Diagnostic archives were saved locally under ~/Work/oai-test-evidence/:

- oai-multi-cell-24prb-diagnostic-20261010-141308.tar.gz
- oai-multi-cell-actors-diagnostic-20261010-185550.tar.gz

These local archives are not included in Git. They contain selected
diagnostic events and container state; avoid publishing UE credentials
or unrestricted authentication logs.

### Contributor continuation

For case 6, establish stable simultaneous UE sessions first, then run
independent traffic flows and collect per-node MAC/KPM reports.
Record process health, queue growth, CPU usage, traffic results and
subscription cleanup. CPU scheduling changes or a stronger/distributed
host need fresh validation.

For cases 7 and 8, a control acknowledgement alone does not prove
handover or scheduler execution. Collect the corresponding UE/session
or scheduler evidence and verify the resulting data-plane behavior.

For cases 9 and 10, contributors with physical equipment should document
hardware models, software versions, RF setup, measurement method,
acceptance criteria and cleanup alongside their results.
