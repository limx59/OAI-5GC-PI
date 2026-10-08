# Multi-node QoS monitoring experiment

## Purpose and environment

Validated on an ARM64 Raspberry Pi on 2026-10-07, local Pacific time.
Test independent low-throughput alert state for each node and DL/UL metric.

Run all commands from the project root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Requirements: Python 3, Docker Compose, sudo access, SCTP support and the
existing external oai-pi-flexric-lab bridge, subnet 172.29.0.0/24.
Stop other deployments occupying the same lab addresses.
Open5GS, UERANSIM and ReDroid are outside this experiment.

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Emulator | limx59/flexric-emulator:arm64-multi-agent |
| xApp | limx59/flexric-xapp:arm64-multi-agent |

Fixed xApp image-index digest:
sha256:413acdbecc5c6cf04b878d1f3ac9de4cf1dd9a8a7bc1a4e5433228b0dc808bbf

The earlier xApp image used digest
sha256:aec1fb4b061a53a11a653df0b622b0167135e6195cdaccb831a9dfe215779bd3.
The arm64-multi-agent xApp tag was updated after the QoS fix.
Earlier CSV and topology results refer to that earlier upload.

## Failure and diagnosis

The initial three-Agent test received repeated DL/UL measurements for
nodes 1, 2 and 3, all below the test threshold, but produced no alerts.
All three subscription deletion responses arrived normally.

Source inspection found a single static hndlr_kpm_cb pointer in
flexric/src/xApp/swig/swig_wrapper.cpp. report_kpm_sm replaces it on each
subscription, and sm_cb_kpm dispatches every node's report through it.

The final Python callback therefore receives interleaved node reports.
The old QoS evaluate method reset all tracked keys absent from the current
report, including keys belonging to other nodes. Alternating reports
prevented counters from reaching the required two consecutive reports.

The Python fix in test/xapp/xapp_qos_watch.py:

- Captures the reporting node identity before decoding the indication.
- Restricts missing-data resets to keys belonging to that node.
- Locks report handling to protect the callback's node context.
- Preserves the existing node/metric alert and recovery behavior.

The native SDK callback routing was not changed.

## Logic regression tests

The reusable test uses synthetic indication objects with the real recorder
and QoS code, substituting the SDK-facing module. It needs no Docker or SDK.

```bash
python3 -B test/flexric/test-qos-node-state.py
```

All three cases passed:

- Interleaved reports produce six independent alerts, without duplicates.
- Empty reports reset only the reporting node and allow subsequent re-alerts.
- At-threshold measurements recover only the reporting node.

These are logic tests, not live recovery or missing-data fault injection.

## Build and initial local validation

Build the corrected xApp image:

```bash
sudo docker build \
  -f docker/flexric/Dockerfile \
  --target xapp --build-arg BUILD_JOBS=2 \
  -t oai-pi-flexric-xapp:qos-multi-agent-test .
```

Start either topology using the deployment commands below. To test the
local xApp image before publication, use:

```bash
python3 test/flexric/validate-qos-watch.py \
  --scenario multi-agent \
  --xapp-image oai-pi-flexric-xapp:qos-multi-agent-test \
  --pull-policy never \
  --output-dir /tmp/flexric-qos-fixed-validation
```

For the dual-RIC topology, change --scenario to multi-ric.
Both local-image scenarios passed.

Publish the validated image:

```bash
sudo docker tag \
  oai-pi-flexric-xapp:qos-multi-agent-test \
  limx59/flexric-xapp:arm64-multi-agent
```

```bash
sudo docker push limx59/flexric-xapp:arm64-multi-agent
```

Existing multi-agent and multi-RIC Compose overlays already reference
this tag, so no image-name change was needed.

## Published-image test: single RIC, three Agents

Remove local image overrides before reproducing the published-image run:

```bash
unset FLEXRIC_RIC_IMAGE FLEXRIC_EMULATOR_IMAGE FLEXRIC_XAPP_IMAGE
```

RIC A is 172.29.0.10. Agents 1, 2 and 3 are 172.29.0.20 through .22.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  up -d --no-build --pull always --force-recreate \
  ric emulator emulator-2 emulator-3
```

After Agent registration, run:

```bash
python3 test/flexric/validate-qos-watch.py \
  --scenario multi-agent \
  --output-dir /tmp/flexric-dockerhub-qos-validation
```

Clean up before switching topologies:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  down
```

## Published-image test: two RICs

RIC A manages nodes 1 and 2. RIC B, 172.29.0.11, manages node 3.
Each RIC's two test cases run sequentially.

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  up -d --no-build --pull always --force-recreate \
  ric ric-2 emulator emulator-2 emulator-3
```

```bash
python3 test/flexric/validate-qos-watch.py \
  --scenario multi-ric \
  --output-dir /tmp/flexric-dockerhub-qos-validation
```

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.multi-ric.yaml \
  down
```

Both published-image scenarios passed and all experiment containers were
removed. The external bridge and existing core deployment were preserved.

## Checks and observed results

The validator defaults to the published xApp image and --pull-policy always.
Each case runs an xApp for its usual ten-second monitoring period after
subscription setup. The Docker command has a 60-second timeout including pull.

Both cases set XAPP_QOS_LOW_REPORTS=2:

- alerts: threshold 1000000000.0, deliberately above observed emulator values.
- no-alerts: threshold 0.0, below or equal to valid nonnegative values.

These are test thresholds in agent-reported units, not operational SLAs.

The validator checks expected subscriptions, finite nonnegative means,
positive sample counts and observations for every node/metric pair.
High-threshold alerts must occur after exactly two printed observations,
once per pair. The zero-threshold run must produce no alerts.
Unexpected callback errors, UNKNOWN or RECOVERY events fail these cases.
All expected subscription deletion responses must be received.

| Published-image scenario | RIC | Nodes | High-threshold alerts | Zero-threshold alerts |
| --- | --- | --- | --- | --- |
| Multi-agent | A | 1, 2, 3 | 6 | 0 |
| Multi-RIC | A | 1, 2 | 4 | 0 |
| Multi-RIC | B | 3 | 2 | 0 |

Local evidence directories:

- Initial failure: /tmp/flexric-dockerhub-qos-validation/multi-agent-vl9ydi0s
- Fixed local single RIC: /tmp/flexric-qos-fixed-validation/multi-agent-7u4sxadp
- Fixed local dual RIC: /tmp/flexric-qos-fixed-validation/multi-ric-rzaol26s
- Published dual RIC: /tmp/flexric-dockerhub-qos-validation/multi-ric-ivihfhnn
- Published single RIC: /tmp/flexric-dockerhub-qos-validation/multi-agent-51a8jx8r

Logs use ric-a-alerts.log and ric-a-no-alerts.log; dual-RIC runs also
produce the corresponding ric-b files. Future runs use unique directories.
Logs remain outside Git. The validator attempts to remove only its own
temporary xApp container on completion, failure or timeout.

## Limits

Live tests use synthetic emulator throughput. They do not establish
per-UE SLA compliance, OAI integration, real QoS faults or control actions.
Low throughput may represent idle traffic demand.

Recovery and missing-data isolation were exercised by the logic tests;
the live scenarios cover sustained alerts and no-alert behavior.
An absence of arriving indications does not trigger a stale-data alarm.
The SDK still shares one KPM callback, so applications requiring distinct
handlers per subscription need additional SDK work.
