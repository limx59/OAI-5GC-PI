# OAI KPM subscription cleanup regression

## Purpose and validated environment

Run repeated KPM CSV recording and subscription cleanup while an OAI
RFSim UE sends and receives UDP traffic through an existing Open5GS core.

The gNB contains its E2 Agent. The RIC and recorder xApp run separately.
This experiment uses one UE and gNB node 3584, PLMN 001/01.

The published recorder and three-round regression wrapper passed on an
ARM64 Raspberry Pi on 2026-10-08, Pacific time. The run reused a local
radio-statistics gNB image; see the observed environment below.

This experiment extends the
[OAI KPM recording workflow](README.oai-kpm-recording.md).

Requirements: Python 3, Docker Compose, sudo access, SCTP support,
the existing Open5GS core and a prepared local UE configuration.
The subscriber and UE configuration must already match.
Do not print or commit UE authentication credentials.

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

## Images and networks

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64 |
| gNB | limx59/oai-gnb:arm64 |
| NR UE and traffic server | limx59/oai-nr-ue:arm64 |
| Recorder xApp | limx59/flexric-xapp:arm64-subscription-cleanup |

Validated recorder digest:

sha256:cc82b9a45449d07c6b3ff11d527d4555f4f02375f8a6fb0d28d7128ad98accb6

Tags are mutable. Pull explicitly before testing.
The validator records the recorder RepoDigests in its evidence directory.

| Endpoint | Network | Address |
| --- | --- | --- |
| RIC | oai-pi-flexric-lab | 172.29.0.10 |
| gNB E2/RFSim | oai-pi-flexric-lab | 172.29.0.30 |
| gNB N2/N3 | docker_open5gs_default | 172.22.0.150 |
| UPF N3 | docker_open5gs_default | 172.22.0.8 |
| Traffic server | docker_open5gs_default | 172.22.0.151 |

The external lab bridge uses 172.29.0.0/24.
Stop other lab deployments occupying the RIC or gNB addresses.
Check that .150 and .151 are available on the core bridge.
Preserve the existing Open5GS, UERANSIM and ReDroid deployment.

```bash
sudo docker network inspect oai-pi-flexric-lab docker_open5gs_default \
  --format '{{.Name}}{{println}}{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

Confirm the local UE configuration exists without displaying it:

```bash
test -f deploy/oai-flexric/config/oai/ue.conf \
  && echo "UE configuration exists"
```

## Start the RIC, gNB and UE

For a deployment using the published base images:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  up -d --no-build --pull always ric gnb
```

Verify NG Setup and E2 Setup before starting the UE:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color gnb |
  grep -E 'NGSetupResponse|associated AMF|E2 SETUP RESPONSE|Assertion'
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue up -d --no-build --pull always nrue
```

Inspect selected UE events only; raw OAI logs may contain credentials:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color nrue |
  grep -E 'Registration Accept|PDU Session Establishment Accept|TUN Interface|Assertion'
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ip -4 -o addr show dev oaitun_ue1
```

Expected: successful registration, PDU session establishment and one
IPv4 address on oaitun_ue1. Address allocation can change.
The validator discovers the address automatically.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ping -I oaitun_ue1 -c 5 -W 5 192.168.100.1
```

When reusing an existing lab, inspect its images and Compose overrides.
The base startup commands can replace an overridden gNB with the
published image.

## Start the independent traffic server

The traffic server runs separately from the OAI Compose services.
After confirming 172.22.0.151 is available:

```bash
sudo docker run -d --rm --pull always --name oai-pi-oai-traffic \
  --network docker_open5gs_default --ip 172.22.0.151 \
  --cap-add NET_ADMIN --entrypoint sh limx59/oai-nr-ue:arm64 \
  -c 'ip route add 192.168.100.0/24 via 172.22.0.8 &&
      exec timeout --signal=INT --kill-after=5s 900s \
      iperf3 -s -B 172.22.0.151'
```

Traffic traverses the UE TUN, RFSim, gNB and UPF.
The server route returns UE subnet traffic through the UPF.
Reuse the server if it is already running.
It expires after 900 seconds and removes itself on exit.
Restart it if the deadline passes before testing.

## Pull the recorder and run the regression

```bash
sudo docker pull limx59/flexric-xapp:arm64-subscription-cleanup
```

Run three consecutive uplink/downlink rounds:

```bash
python3 test/flexric/validate-oai-kpm-subscription-cleanup.py \
  --xapp-image limx59/flexric-xapp:arm64-subscription-cleanup \
  --pull-policy never \
  --rounds 3 \
  --output-dir /tmp/oai-dockerhub-kpm-subscription-cleanup
```

The wrapper invokes validate-oai-kpm-recording.py sequentially.
Each round runs uplink followed by downlink.
A failed round stops the regression and returns a nonzero exit code.

The explicit pull selects the image before testing.
--pull-policy never reuses that local image throughout the run.

| Option | Description |
| --- | --- |
| --xapp-image | Defaults to limx59/flexric-xapp:arm64-subscription-cleanup |
| --pull-policy | `always`: pull in the first round only; `never`: use the existing local image throughout |
| --rounds | Sequential rounds; defaults to 3 and must be at least 1 |
| --output-dir | Parent directory for test evidence |

To run one uplink/downlink pair directly:

```bash
python3 test/flexric/validate-oai-kpm-recording.py \
  --xapp-image limx59/flexric-xapp:arm64-subscription-cleanup \
  --pull-policy never \
  --output-dir /tmp/oai-dockerhub-kpm-subscription-cleanup
```

Always specify --xapp-image for the underlying recording validator;
its default still selects arm64-multi-agent.

## Checks and expected output

Each round runs separate 30-second UDP uplink and downlink transfers,
offering 1 Mbit/s with 1200-byte datagrams.
The recorder starts three seconds after each traffic process starts,
records for approximately ten seconds and deletes its subscription.

The recording validator checks:

- Positive iperf receiver bytes and bitrate.
- Exactly one subscription to the expected node and one deletion response.
- Expected node identity and PLMN 001/01.
- Both DL and UL metrics with complete, finite nonnegative numeric values.
- CSV reception timestamps within the traffic subprocess window.
- At least two positive active-direction reports after the first report.
- Absence of detected callback errors, malformed rows and unsupported formats.

Successful directional output includes:

```text
PASS: uplink, node=3584, ... subscription cleanup complete
PASS: downlink, node=3584, ... subscription cleanup complete
```

After three successful rounds:

```text
PASS: all 3 uplink/downlink regression rounds completed.
```

All six directional tests must pass.
Exact CSV row counts and bitrates need not match the observed results.

## Observed environment and results

The published recorder was explicitly pulled before the wrapper run.
The existing RIC, gNB and UE remained running.

| Component | Image used |
| --- | --- |
| RIC | limx59/flexric-ric:arm64 |
| gNB | oai-pi-oai-gnb:radio-stats-test |
| NR UE and traffic server | limx59/oai-nr-ue:arm64 |
| Recorder | limx59/flexric-xapp:arm64-subscription-cleanup |

The running gNB used the base Compose file plus
/tmp/compose.oai-radio-stats-test.yaml. The override contained:

```yaml
services:
  gnb:
    image: oai-pi-oai-gnb:radio-stats-test
```

That local gNB image and temporary override are not distributed by this
guide. The base published-gNB preparation steps above were not rerun for
this regression.

UE address: 192.168.100.251. gNB node ID: 3584.

| Round | Direction | CSV rows | Positive later reports | Receiver bitrate | Cleanup |
| --- | --- | --- | --- | --- | --- |
| 1 | Uplink | 18 | 8 | 973906 bit/s | PASS |
| 1 | Downlink | 20 | 9 | 999965 bit/s | PASS |
| 2 | Uplink | 20 | 9 | 959380 bit/s | PASS |
| 2 | Downlink | 20 | 9 | 996217 bit/s | PASS |
| 3 | Uplink | 18 | 8 | 934752 bit/s | PASS |
| 3 | Downlink | 20 | 9 | 999012 bit/s | PASS |

All six directional tests and the regression wrapper passed.

Evidence directories:

- /tmp/oai-dockerhub-kpm-subscription-cleanup/oai-ojtvkc5l
- /tmp/oai-dockerhub-kpm-subscription-cleanup/oai-ki3fdkvi
- /tmp/oai-dockerhub-kpm-subscription-cleanup/oai-59n3ivob

The earlier local-recorder regression also passed three rounds.
The table above describes the published-recorder wrapper run.

## Evidence and archiving

Each recording-validator invocation creates a unique evidence directory.

Evidence includes:

- uplink.csv and downlink.csv.
- Corresponding recorder xApp logs.
- iperf JSON and stderr logs.
- image-pull.log and image-digests.json.
- summary.json.

With --pull-policy never, image-pull.log records that pulling was skipped.

Archive the evidence in the home directory:

```bash
tar -czf "$HOME/oai-dockerhub-kpm-subscription-cleanup-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp oai-dockerhub-kpm-subscription-cleanup
```

This archive command completed successfully after the observed run.
Keep raw logs, CSV files and archives outside Git.

The validator removes its temporary recorder container.
The RIC, gNB and UE remain running until explicit cleanup.
The traffic server remains until stopped or its timeout expires.

## Cleanup

Stop the independent traffic server:

```bash
sudo docker stop oai-pi-oai-traffic
```

If its deadline already removed it, confirm it is absent instead.

Remove the OAI experiment containers:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue --profile tools down
```

Retain external networks, the subscriber, local UE configuration and
the existing core deployment.

## Scope and limitations

Validated: three sequential uplink/downlink rounds of RFSim traffic,
KPM CSV recording and normal subscription cleanup using the published
recorder against the observed local-gNB environment.

A repeat using the base published gNB remains unvalidated.

Three passing rounds do not establish absence of every concurrency race.
Abrupt xApp failure, concurrent subscription cleanup, RIC failover and
automatic subscription restoration are outside this regression.

Reception timestamps are not source measurement timestamps.
The traffic subprocess window includes connection setup and completion;
the check does not prove precise alignment with packet transfer intervals.

Positive reports do not establish measurement accuracy or exact
equivalence between iperf and KPM values.
Physical RF, per-UE identity mapping, real handover, scheduler enforcement,
throughput benchmarking and latency benchmarking remain unvalidated.

## Source-level subscription cleanup regression

Validated on an ARM64 Raspberry Pi on 2026-10-09, Pacific time.
This independent test compiles the relevant FlexRIC source files and
runs through Docker Compose. It does not enable the upstream UNIT_TEST
suite or require a running RIC, gNB, UE or Open5GS core.

Requirements: Docker Compose and network access to obtain the Debian
base image and build packages. Run from the repository root.

### Pull and run the published regression image

Pull the regression image from Docker Hub:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.subscription-cleanup-test.yaml \
  pull regression
```

Run the test using the explicitly pulled image:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.subscription-cleanup-test.yaml \
  run --rm --no-deps --pull never regression
```

Published image:
limx59/flexric-xapp:arm64-subscription-cleanup-regression.

Validated image-index digest:

sha256:84be0994893389707197b13b560bf883d4c6a2f9a8915528b28f5bc7b4b056fb

Tags are mutable. Pull explicitly before testing.
This image contains a CTest executable and is separate from the Python
recorder image used by the RFSim workflow.

To test source changes in the current checkout, build before running:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.subscription-cleanup-test.yaml \
  build regression
```

Then run the same Compose command with --pull never. Building locally
replaces the local image associated with the published tag. Pull again
before validating the Docker Hub image.

The test container has networking disabled and is removed after the run.
No OAI experiment containers or core services are started or stopped.

### Checks and pass criteria

The test checks:

- An ACK signalled before entering the wait is preserved.
- Three successive ACK/wait cycles consume and reset the ACK flags.
- Four pending deletion requests with the same event type remain distinct
  when the request ID, instance ID or RAN function ID differs.
- Requests can be removed independently by event identity or descriptor.
- The removed descriptor matches the requested event.
- Changing wait_ms does not change the request identity.
- Remaining requests stay discoverable and removed requests are absent.

Assertions remain enabled in the Release build.
CTest applies a ten-second timeout.

Expected successful output includes:

```text
PASS: early ACK preserved and consumed across repeated waits
PASS: same-type pending requests remain independently removable
100% tests passed, 0 tests failed out of 1
```

Both checks must complete and the Compose command must exit successfully.

### Observed result and lookup fix

The initial source-level run failed while checking event lookup after
removing a request. The bimap-specific search helper passed a tree
iterator to the event comparison callback instead of an event key.

find_pending_event_ev in flexric/src/xApp/pending_event_xapp.c now
searches the right-hand tree using find_if, which passes the event keys
to the comparison callback. The existing mutex and event identity
comparison are retained.

After rebuilding the regression image, both checks passed.
The published regression image was subsequently pulled through Compose
and tested on 2026-10-09. Both checks passed again:
one CTest test completed with zero failures.

This source lookup change has not yet been incorporated into the
published recorder image. The earlier published-image RFSim results
validate that image's existing behavior.

### Scope and limitations

This is a deterministic source-level regression for an ACK received
before the wait and for pending-request identity, lookup and removal.

It does not exercise SCTP, actual subscription request/response traffic,
registration-before-send ordering, concurrent callbacks, timeout
recovery or every possible race. It supplements the RFSim regression;
it does not replace an integration run with a rebuilt recorder image.
