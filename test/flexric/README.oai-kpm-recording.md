# OAI UE traffic KPM CSV recording

## Purpose and validated environment

Validated on an ARM64 Raspberry Pi on 2026-10-08, Pacific time.
Record OAI gNB KPM measurements while an RFSim UE sends or receives UDP
traffic through the existing Open5GS core.

The gNB contains its E2 Agent. The RIC and recorder xApp run separately.
This experiment uses one UE and gNB node 3584, PLMN 001/01.
It extends the [OAI end-to-end workflow](../../deploy/oai-flexric/README.e2e.md).

Requirements: Python 3, Docker Compose, sudo access, SCTP support,
the existing Open5GS core and a prepared local UE configuration.
The dedicated subscriber and UE configuration must already match.
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
| CSV recorder xApp | limx59/flexric-xapp:arm64-multi-agent |

Validated xApp image-index digest:

sha256:fa5e6e52d37850726d7b9465d0bbbfb4ad911a29ece328d2101cec2ee6a1ca96

The experiment pulled published images. No image source changes, rebuild
or new upload were needed. Tags are mutable; the validator records the
pulled xApp RepoDigests in its evidence directory.

| Endpoint | Network | Address |
| --- | --- | --- |
| RIC | oai-pi-flexric-lab | 172.29.0.10 |
| gNB E2/RFSim | oai-pi-flexric-lab | 172.29.0.30 |
| gNB N2/N3 | docker_open5gs_default | 172.22.0.150 |
| UPF N3 | docker_open5gs_default | 172.22.0.8 |
| Traffic server | docker_open5gs_default | 172.22.0.151 |
| UE TUN in this run | UE PDU session | 192.168.100.248 |

The lab bridge uses 172.29.0.0/24. Stop other lab deployments occupying
the RIC or gNB addresses. Check that .150 and .151 are free on the core
bridge. Preserve the existing Open5GS, UERANSIM and ReDroid deployment.

```bash
sudo docker network inspect oai-pi-flexric-lab docker_open5gs_default \
  --format '{{.Name}}{{println}}{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

Confirm config/oai/ue.conf exists locally without displaying its contents.

## Start the RIC, gNB and UE

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

Expected: Registration Accept, PDU Session Establishment Accept and
a configured oaitun_ue1. UE address allocation can change.
The validator reads the TUN address automatically.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ping -I oaitun_ue1 -c 5 -W 5 192.168.100.1
```

Observed: 5/5 replies, zero loss, average RTT 158.460 ms.

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

Traffic goes through the UE TUN, RFSim, gNB and UPF.
The server route returns UE subnet traffic through the UPF.
The server automatically removes itself on exit and expires after
900 seconds; restart it if that deadline has passed.

## Run the reusable recording validator

```bash
python3 test/flexric/validate-oai-kpm-recording.py \
  --output-dir /tmp/oai-dockerhub-kpm-recording
```

Optional arguments: --xapp-image, --server and --node-id.
Defaults select the published xApp tag, 172.22.0.151 and node 3584.

The validator:
- Reads exactly one IPv4 address from oaitun_ue1.
- Pulls the xApp image and records its RepoDigests.
- Runs separate 30-second UDP uplink and downlink transfers, offering
  1 Mbit/s with 1200-byte datagrams.
- Binds each client to the UE address and oaitun_ue1.
- Starts the recorder three seconds after starting each traffic process.
- Reuses xapp_kpm_recorder.py, which subscribes and records for about
  ten seconds before deleting its subscription.
- Checks positive iperf receiver bytes and bitrate.
- Requires exactly one subscription to node 3584 and one deletion response.
- Rejects callback errors, malformed rows and unsupported formats.
- Checks node identity, PLMN 001/01, both DL/UL metrics, complete numeric
  records, finite nonnegative values and UTC reception timestamps.
- Checks CSV timestamps fall within the traffic subprocess window.
- Excludes the first report timestamp from the active-direction positive
  count and requires at least two later positive reports.

Reception timestamps are not source measurement timestamps. The traffic
subprocess window includes connection setup and completion; the check
does not prove precise alignment with packet transfer intervals.

Traffic and recorder logs are preserved. Traffic has an in-container
45-second timeout and a host-side 55-second timeout. The recorder has a
60-second timeout. Its uniquely named container is removed in cleanup.
The script leaves the RIC, gNB, UE and traffic server for explicit cleanup.

## Observed results

Evidence directory:

/tmp/oai-dockerhub-kpm-recording/oai-zo5g_h65

| Result | Uplink | Downlink |
| --- | --- | --- |
| UE address | 192.168.100.248 | 192.168.100.248 |
| gNB node ID | 3584 | 3584 |
| CSV rows | 18 | 20 |
| DL / UL metric rows | 9 / 9 | 10 / 10 |
| Report timestamps | 9 | 10 |
| Positive active-direction reports after first | 8 | 9 |
| Receiver bitrate | 950,162 bit/s | 997,423 bit/s |
| Lost / total datagrams | 13 / 3033 | 12 / 3132 |
| Reported packet loss | 0.429% | 0.377% |
| Final receiver jitter | 8.433 ms | 10.865 ms |
| Subscription deletion responses | 1 | 1 |

First report values, in agent-reported units:

| Direction | DRB.UEThpDl | DRB.UEThpUl |
| --- | --- | --- |
| Uplink test | 9.952 | 6714.496 |
| Downlink test | 8633.272 | 14168.752 |

The initial values were unusually high. They are preserved in summary.json
and excluded from the later-positive report check. No measurement-accuracy
claim follows from these results.

Evidence includes uplink.csv, downlink.csv, the corresponding xApp logs,
iperf JSON and stderr logs, image-pull.log, image-digests.json and summary.json.
CSV row counts can vary; the validator does not require these exact counts.
Evidence remains outside Git.

## Cleanup

```bash
sudo docker stop oai-pi-oai-traffic
```

If the deadline already removed the server, confirm it is absent instead.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue --profile tools down
```

The traffic server and all three OAI experiment containers were removed
after this run. External networks, the subscriber, local UE configuration
and the existing core deployment were retained.

## Scope and limitations

Validated: CSV recording of OAI KPM during separate RFSim UE traffic
directions, node/metric coverage, positive later activity and subscription
cleanup using a published xApp image.

Small UDP losses were observed; their cause was not established.
This is a short functional experiment, not a throughput or latency
benchmark. No exact equivalence between iperf and KPM values is asserted.
Per-UE identity mapping, measurement accuracy, physical RF, real handover,
scheduler enforcement and energy savings remain unvalidated.
