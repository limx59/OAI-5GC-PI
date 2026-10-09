# OAI KPM subscription cleanup regression

## Purpose and environment

Test repeated KPM CSV recording and subscription cleanup while an OAI
RFSim UE sends and receives traffic through an existing Open5GS core.

The original three-round regression passed on an ARM64 Raspberry Pi
on 2026-10-08, Pacific time.

Run all commands from the project root.

Requirements:

- Python 3, Docker Compose, sudo access and SCTP support.
- An existing Open5GS core.
- A prepared config/oai/ue.conf matching the configured subscriber.
- The recording validator and regression wrapper included in this repository.

Do not print or commit UE authentication credentials.

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64 |
| gNB | limx59/oai-gnb:arm64 |
| NR UE and traffic server | limx59/oai-nr-ue:arm64 |
| Recorder xApp | limx59/flexric-xapp:arm64-subscription-cleanup |

The original results were obtained using the local test image before
upload. A separate run using the pulled image and the new regression
wrapper has not yet been recorded.

## Prepare the OAI environment

See the [OAI KPM recording workflow](README.oai-kpm-recording.md)
for the existing environment prerequisites.

| Endpoint | Network | Address |
| --- | --- | --- |
| RIC | oai-pi-flexric-lab | 172.29.0.10 |
| gNB E2/RFSim | oai-pi-flexric-lab | 172.29.0.30 |
| gNB N2/N3 | docker_open5gs_default | 172.22.0.150 |
| UPF N3 | docker_open5gs_default | 172.22.0.8 |
| Traffic server | docker_open5gs_default | 172.22.0.151 |

Stop other lab deployments occupying these addresses.
Preserve the existing Open5GS, UERANSIM and ReDroid deployment.

Inspect network address usage:

```bash
sudo docker network inspect oai-pi-flexric-lab docker_open5gs_default \
  --format '{{.Name}}{{println}}{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

Confirm the prepared UE configuration exists without displaying it:

```bash
test -f config/oai/ue.conf && echo "UE configuration exists"
```

Start the RIC and gNB:

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

Start the UE:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue up -d --no-build --pull always nrue
```

Inspect selected UE events:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color nrue |
  grep -E 'Registration Accept|PDU Session Establishment Accept|TUN Interface|Assertion'
```

Verify the UE TUN address:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ip -4 -o addr show dev oaitun_ue1
```

Expected: successful registration, PDU session establishment and an IPv4
address on oaitun_ue1. The validator discovers this address automatically.

Check connectivity:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ping -I oaitun_ue1 -c 5 -W 5 192.168.100.1
```

## Start the independent traffic server

After confirming 172.22.0.151 is available, start the server.
Reuse the experiment traffic server if it is already running.

```bash
sudo docker run -d --rm --pull always --name oai-pi-oai-traffic \
  --network docker_open5gs_default --ip 172.22.0.151 \
  --cap-add NET_ADMIN --entrypoint sh limx59/oai-nr-ue:arm64 \
  -c 'ip route add 192.168.100.0/24 via 172.22.0.8 &&
      exec timeout --signal=INT --kill-after=5s 900s \
      iperf3 -s -B 172.22.0.151'
```

Traffic traverses the UE TUN, RFSim, gNB and UPF.
The server expires after 900 seconds and removes itself on exit.
Restart it if it expires before a subsequent test.

## Pull the recorder image

```bash
sudo docker pull limx59/flexric-xapp:arm64-subscription-cleanup
```

The tag is mutable. The validator records image RepoDigests in each
evidence directory for version tracking.

## Run the regression

Run three consecutive rounds:

```bash
python3 test/flexric/validate-oai-kpm-subscription-cleanup.py \
  --xapp-image limx59/flexric-xapp:arm64-subscription-cleanup \
  --pull-policy never \
  --rounds 3 \
  --output-dir /tmp/oai-kpm-subscription-cleanup
```

The wrapper invokes validate-oai-kpm-recording.py sequentially.
Each round runs uplink followed by downlink.
Any failed round stops the regression immediately.

The image is pulled explicitly before testing, so --pull-policy never
reuses that image throughout the run.

| Option | Description |
| --- | --- |
| --xapp-image | Recorder image; defaults to limx59/flexric-xapp:arm64-subscription-cleanup |
| --pull-policy | always pulls in the first round; never uses the existing local image |
| --rounds | Number of sequential rounds; defaults to 3 |
| --output-dir | Parent directory for test evidence |

To run a single uplink/downlink pair directly:

```bash
python3 test/flexric/validate-oai-kpm-recording.py \
  --xapp-image limx59/flexric-xapp:arm64-subscription-cleanup \
  --pull-policy never \
  --output-dir /tmp/oai-kpm-subscription-cleanup
```

Always specify --xapp-image when invoking the underlying recording
validator, whose default still selects arm64-multi-agent.

## Checks and expected output

Each round runs separate 30-second UDP uplink and downlink transfers,
offering 1 Mbit/s with 1200-byte datagrams.
The recorder starts three seconds after traffic starts and records for
approximately ten seconds before deleting its subscription.

The recording validator checks:

- Positive iperf receiver bytes and bitrate.
- Expected gNB node identity and PLMN 001/01.
- DL and UL metric coverage with finite nonnegative numeric values.
- CSV reception timestamps within the traffic subprocess window.
- At least two positive active-direction reports after the first report.
- Expected subscription deletion response and completed cleanup.
- Absence of detected callback errors and malformed records.

Successful directional output includes:

```text
PASS: uplink, node=3584, ... subscription cleanup complete
PASS: downlink, node=3584, ... subscription cleanup complete
```

After three successful rounds, the wrapper prints:

```text
PASS: all 3 uplink/downlink regression rounds completed.
```

A successful regression requires all six directional tests to pass.

## Observed results

The original local-image regression produced the following results:

| Round | Direction | CSV rows | Positive later reports | Receiver bitrate | Cleanup |
| --- | --- | --- | --- | --- | --- |
| 1 | Uplink | 18 | 8 | 952510 bit/s | PASS |
| 1 | Downlink | 20 | 9 | 996114 bit/s | PASS |
| 2 | Uplink | 18 | 8 | 979603 bit/s | PASS |
| 2 | Downlink | 18 | 8 | 998182 bit/s | PASS |
| 3 | Uplink | 20 | 9 | 951373 bit/s | PASS |
| 3 | Downlink | 20 | 9 | 990369 bit/s | PASS |

All six tests passed for gNB node 3584.
CSV row counts may vary; exact equality with the table is not required.

These results validate the original sequential recording-validator runs.
They do not represent a completed run of the subsequently added wrapper.

## Evidence and archiving

Each round prints a unique evidence directory under --output-dir.

Evidence includes:

- uplink.csv and downlink.csv.
- Corresponding recorder xApp logs.
- iperf JSON and stderr logs.
- image-pull.log and image-digests.json.
- summary.json.

With --pull-policy never, image-pull.log records that pulling was skipped.

Archive the evidence after testing:

```bash
tar -czf "/tmp/oai-kpm-subscription-cleanup-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp oai-kpm-subscription-cleanup
```

Copy the archive to persistent team test-artifact storage before /tmp
is cleared. Keep raw logs, CSV files and archives outside Git.

The validator removes its temporary recorder container.
The RIC, gNB, UE and traffic server remain available until explicit
cleanup or, for the traffic server, its timeout expires.

## Cleanup

Stop the traffic server:

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

## Limits

This is a short functional regression of RFSim traffic, KPM recording
and subscription cleanup. Three passing rounds do not establish absence
of every concurrency race.

Reception timestamps are not source measurement timestamps.
The traffic subprocess window includes connection setup and completion;
the check does not prove precise alignment with packet transfer intervals.

Positive reports do not establish measurement accuracy or exact
equivalence between iperf and KPM values.

Physical RF, per-UE identity mapping, real handover, scheduler enforcement,
throughput benchmarking and latency benchmarking are outside this test.
