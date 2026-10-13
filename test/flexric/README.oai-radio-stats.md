# OAI UE traffic MAC/RLC/PDCP reporting

## Purpose and validated environment

Validated on an ARM64 Raspberry Pi on 2026-10-09, Pacific time.
Check delivery of nonempty MAC, RLC and PDCP reports while one OAI
RFSim UE sends and receives UDP traffic through an existing Open5GS core.

The experiment uses gNB node 3584, PLMN 001/01.
It extends the [OAI KPM recording workflow](README.oai-kpm-recording.md).

Requirements: Python 3, Docker Compose, sudo access, SCTP support,
the existing Open5GS core, external Docker networks and a prepared UE
configuration matching the configured subscriber.
Do not print or commit UE authentication credentials.

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

## Independent components and communication

The RIC, gNB, UE, recorder xApp and traffic server run in separate
containers. The gNB includes its E2 Agent.

- The gNB connects to the RIC over E2.
- The xApp connects to the RIC and subscribes to MAC/RLC/PDCP reports.
- The UE connects to the gNB through RFSim.
- The gNB connects to the existing Open5GS core.
- Traffic passes between the UE TUN and the independent iperf server
  through RFSim, the gNB and UPF.

The host-side Python validator orchestrates traffic and temporary xApp
containers and checks the collected evidence. It uses Compose exec for
the UE and Docker run for the xApp. It does not deploy the core.

## Images and networks

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64 |
| gNB | limx59/oai-gnb:arm64-radio-stats |
| NR UE and traffic server | limx59/oai-nr-ue:arm64 |
| Radio statistics xApp | limx59/flexric-xapp:arm64-subscription-cleanup |

Validated gNB digest:

sha256:c98427aef6794d7e00ab9368b6bd35819b81fc5e7deced4c3b040eedb90e82e3

Validated xApp image-index digest:

sha256:195b2136818b58d2684f7499e822d810fd1d6ad0712dfedee020e52b049e88fc

Tags are mutable. Pull explicitly before testing.
The validator records the xApp RepoDigests in its evidence directory.

| Endpoint | Network | Address |
| --- | --- | --- |
| RIC | oai-pi-flexric-lab | 172.29.0.10 |
| gNB E2/RFSim | oai-pi-flexric-lab | 172.29.0.30 |
| gNB N2/N3 | docker_open5gs_default | 172.22.0.150 |
| UPF N3 | docker_open5gs_default | 172.22.0.8 |
| Traffic server | docker_open5gs_default | 172.22.0.151 |

Stop other lab deployments occupying these addresses.
Preserve the existing Open5GS, UERANSIM and ReDroid deployment.

```bash
sudo docker network inspect oai-pi-flexric-lab docker_open5gs_default \
  --format '{{.Name}}{{println}}{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

Confirm the prepared UE configuration exists without displaying it:

```bash
test -f deploy/oai-flexric/config/oai/ue.conf && echo "UE configuration exists"
```

## Pull the published images

Use the base Compose file and the radio-statistics overlay together:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  --profile ue --profile tools pull ric gnb nrue xapp-kpm
```

The overlay selects the published radio-statistics gNB and fixed xApp.
Use --no-build in the following deployment steps.

## Start the RIC, gNB and UE

Start the RIC first:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  up -d --no-build --pull never ric
```

Start the gNB:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  up -d --no-build --pull never --no-deps gnb
```

Verify successful NG Setup and E2 Setup before starting the UE:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  logs --no-color gnb |
  grep -E 'NGSetupResponse|associated AMF|E2 SETUP RESPONSE|Assertion'
```

Expected: NGSetupResponse, associated AMF and E2 SETUP RESPONSE rx.
A running container alone does not establish successful setup.

During the observed replacement of the gNB, E2 Setup initially timed out
against an existing RIC. Stopping the gNB, recreating the RIC and starting
the gNB restored E2 Setup. The cause of that reconnection failure was
not established. Do not start the validator until E2 Setup succeeds.

Start the UE:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  --profile ue up -d --no-build --pull never --no-deps nrue
```

Inspect selected recent events; raw UE logs may contain credentials:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  logs --since 3m --no-color nrue |
  grep -E 'Registration Accept|PDU Session Establishment Accept|TUN Interface|Assertion'
```

Verify the UE TUN address:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  exec -T nrue ip -4 -o addr show dev oaitun_ue1
```

Expected: successful registration, PDU session establishment and one
IPv4 address on oaitun_ue1. The validator discovers the address.

Check connectivity:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  exec -T nrue ping -I oaitun_ue1 -c 5 -W 5 192.168.100.1
```

Observed: 5/5 replies, zero loss, average RTT 251.445 ms.

## Start the independent traffic server

After confirming 172.22.0.151 is available:

```bash
sudo docker run -d --rm --pull always --name oai-pi-oai-traffic \
  --network docker_open5gs_default --ip 172.22.0.151 \
  --cap-add NET_ADMIN --entrypoint sh limx59/oai-nr-ue:arm64 \
  -c 'ip route add 192.168.100.0/24 via 172.22.0.8 &&
      exec timeout --signal=INT --kill-after=5s 900s \
      iperf3 -s -B 172.22.0.151'
```

The return route sends UE subnet traffic through the UPF.
The server expires after 900 seconds and removes itself on exit.
Restart it if it expires before a subsequent test.

## Run the reusable validator

```bash
python3 test/flexric/validate-oai-radio-stats.py \
  --xapp-image limx59/flexric-xapp:arm64-subscription-cleanup \
  --pull-policy never \
  --output-dir /tmp/oai-dockerhub-radio-stats-fixed-validation
```

| Option | Description |
| --- | --- |
| --xapp-image | Defaults to limx59/flexric-xapp:arm64-subscription-cleanup |
| --pull-policy | always pulls the xApp; never uses the existing local image; default always |
| --server | Traffic server IPv4 address; default 172.22.0.151 |
| --node-id | Expected gNB node ID; default 3584 |
| --output-dir | Evidence parent directory; default /tmp/oai-radio-stats |

The explicit image pull above allows --pull-policy never to reuse the
same image during validation.

The script has no --scenario argument. Each invocation runs uplink
followed by downlink; a failed check stops the run.

Each direction offers 1 Mbit/s UDP traffic for 30 seconds with
1200-byte datagrams. The xApp starts three seconds after traffic starts,
waits for node discovery, subscribes to the configured models, collects
reports for ten seconds and deletes its subscriptions.

The validator checks:

- Positive iperf receiver bytes and bitrate.
- Successful xApp exit and an xApp process window within the traffic
  subprocess window.
- Exactly one MAC, RLC and PDCP subscription to the expected node.
- Three subscription deletion responses.
- At least two reports and two nonempty reports for each model.
- Expected report node identity and positive report timestamps.
- Absence of detected callback errors, assertions, Python tracebacks
  and the no-subscriptions diagnostic.

Traffic has a 45-second in-container timeout and a 55-second host timeout.
The xApp has a 60-second timeout. Its temporary container is removed
in cleanup.

Expected successful output includes:

```text
PASS: uplink, node=3584, all three models nonempty, subscription cleanup complete
PASS: downlink, node=3584, all three models nonempty, subscription cleanup complete
```

Both directional tests must pass.
Exact report counts need not match the observed results.

## Fixes and observed results

The gNB Dockerfile previously built and installed only the KPM plugin.
It now also builds mac_sm, rlc_sm and pdcp_sm and installs their libraries
in the configured e2-sm-plugins-kpm directory.

A published-image run initially failed because a subscription log line
was joined to a callback report. The validator's full-line subscription
pattern did not recognize that line.

The radio-statistics xApp now serializes subscription and callback
messages with a Python lock and writes each message with its newline in
one write. This coordinates Python logging; it does not lock SDK C output.

The updated published xApp also includes the pending-event lookup fix
documented in the
[subscription cleanup guide](README.oai-kpm-subscription-cleanup.md).

After pulling the updated published xApp, the following run passed
against limx59/oai-gnb:arm64-radio-stats:

Evidence directory:
/tmp/oai-dockerhub-radio-stats-fixed-validation/oai-ghrgw7bw

UE address: 192.168.100.252. gNB node ID: 3584.

| Direction | Model | Reports | Nonempty reports | Records min / max |
| --- | --- | --- | --- | --- |
| Uplink | MAC | 54 | 54 | 1 / 1 |
| Uplink | RLC | 53 | 53 | 1 / 1 |
| Uplink | PDCP | 48 | 48 | 1 / 1 |
| Downlink | MAC | 70 | 70 | 1 / 1 |
| Downlink | RLC | 74 | 74 | 1 / 1 |
| Downlink | PDCP | 75 | 75 | 1 / 1 |

All three models produced nonempty reports in both directions, and
subscription cleanup passed.

The same published xApp subsequently passed three KPM regression rounds,
six directional tests, with completed subscription cleanup.

## Evidence and archiving

Evidence includes:

- uplink-radio.log and downlink-radio.log.
- Corresponding iperf JSON and stderr logs.
- image-pull.log and image-digests.json.
- summary.json.

With --pull-policy never, image-pull.log records that pulling was skipped.

Archive the evidence in the home directory:

```bash
tar -czf "$HOME/oai-dockerhub-radio-stats-fixed-validation-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /tmp oai-dockerhub-radio-stats-fixed-validation
```

The archive command completed after the observed run.
Keep raw logs, summaries and archives outside Git.

## Cleanup

After completing all tests and archiving their evidence, stop the
independent traffic server:

```bash
sudo docker stop oai-pi-oai-traffic
```

If the deadline already removed the server, confirm it is absent instead.

Remove the OAI experiment containers using both Compose files:

```bash
sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  --profile ue --profile tools down
```

Confirm the remaining containers:

```bash
sudo docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

The traffic server and all three OAI experiment containers were removed
after this run. The running Open5GS core services, UERANSIM and ReDroid
deployment were retained. The cleanup commands do not remove external
networks, the subscriber or local UE configuration.

## Scope and limitations

Validated: MAC/RLC/PDCP report delivery, nonempty record lists and normal
subscription cleanup during separate OAI RFSim UE traffic directions
using the published images.

A nonempty record list does not establish individual counter accuracy,
per-UE identity mapping or a causal relationship to the offered traffic.
Positive report timestamps are not checked for precise traffic alignment.
The process-window check includes traffic setup and completion.

Python logging serialization does not guarantee that SDK C output can
never interleave with a Python message. The validator continues to
require complete subscription and report lines.

Physical RF, real handover, scheduler enforcement, throughput and latency
benchmarking, fault recovery and Kubernetes deployment remain unvalidated.
