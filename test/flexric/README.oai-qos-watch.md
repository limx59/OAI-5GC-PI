# OAI UE traffic QoS monitoring

## Purpose and environment

Validated on an ARM64 Raspberry Pi on 2026-10-08, Pacific time.
Exercise low-throughput alert logic using OAI KPM reports during separate
RFSim UE uplink and downlink UDP transfers.

The test uses one gNB, node 3584, and one UE with address 192.168.100.249
in this run. The OAI lab uses PLMN 001/01.
The validator checks the subscribed node ID; QoS text output does not
expose PLMN fields, so it does not independently assert the report PLMN.

Run commands from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Requirements: Python 3, Docker Compose, sudo access, SCTP support,
the existing Open5GS core and a prepared local config/oai/ue.conf.
Subscriber provisioning and credential preparation are described in
[the end-to-end guide](../../deploy/oai-flexric/README.e2e.md).
Keep credentials local and do not share raw OAI authentication logs.

## Images and network

| Component | Docker Hub image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64 |
| gNB | limx59/oai-gnb:arm64 |
| UE and traffic server | limx59/oai-nr-ue:arm64 |
| QoS xApp | limx59/flexric-xapp:arm64-multi-agent |

Validated xApp image-index digest:

sha256:fa5e6e52d37850726d7b9465d0bbbfb4ad911a29ece328d2101cec2ee6a1ca96

Traffic-server image-index digest:

sha256:230909b7e83f0fecd3ea1cca43d8d3e7b2834858da52367dfcb18f2f396af738

All images were pulled from Docker Hub. No image source changes,
rebuilds or new uploads were required. The traffic server reuses the
UE image's installed iperf3 with an overridden entrypoint.
Its return route exists only inside the temporary container.
The validator records the pulled xApp RepoDigests.

The existing lab bridge is oai-pi-flexric-lab, 172.29.0.0/24.
RIC and gNB use 172.29.0.10 and 172.29.0.30.
The gNB also uses 172.22.0.150 on docker_open5gs_default.
UPF is 172.22.0.8; the traffic server uses 172.22.0.151.
Stop conflicting lab deployments and confirm these addresses are free.
Preserve the existing Open5GS, UERANSIM and ReDroid deployment.

```bash
sudo docker network inspect oai-pi-flexric-lab docker_open5gs_default \
  --format '{{.Name}}{{println}}{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

## Start the OAI lab

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  up -d --no-build --pull always ric gnb
```

Verify NG Setup and E2 Setup:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color gnb |
  grep -E 'NGSetupResponse|associated AMF|E2 SETUP RESPONSE|Assertion'
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue up -d --no-build --pull always nrue
```

Inspect only selected UE events:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color nrue |
  grep -E 'Registration Accept|PDU Session Establishment Accept|TUN Interface|Assertion'
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ip -4 -o addr show dev oaitun_ue1
```

Registration and PDU session establishment succeeded.
The TUN address was 192.168.100.249; future allocations may differ.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ping -I oaitun_ue1 -c 5 -W 5 192.168.100.1
```

Observed: 5/5 replies, zero packet loss, average RTT 138.508 ms.

## Start the independent traffic server

After confirming 172.22.0.151 is free:

```bash
sudo docker run -d --rm --pull always --name oai-pi-oai-traffic \
  --network docker_open5gs_default --ip 172.22.0.151 \
  --cap-add NET_ADMIN --entrypoint sh limx59/oai-nr-ue:arm64 \
  -c 'ip route add 192.168.100.0/24 via 172.22.0.8 &&
      exec timeout --signal=INT --kill-after=5s 900s \
      iperf3 -s -B 172.22.0.151'
```

Traffic crosses the UE TUN, RFSim, gNB and UPF.
The server expires after 900 seconds and removes itself on exit.

## Run the reusable validator

```bash
python3 test/flexric/validate-oai-qos-watch.py \
  --output-dir /tmp/oai-dockerhub-qos-validation
```

Optional arguments: --xapp-image, --server and --node-id.
Defaults select the published xApp tag, server 172.22.0.151 and node 3584.
The validator reads the current UE TUN IPv4 address automatically.

Four cases run sequentially:

| Case | Traffic | Threshold | Required consecutive reports | Expected alerts |
| --- | --- | --- | --- | --- |
| uplink-alerts | UL | 1e9 | 2 | One per DL/UL metric |
| uplink-no-alerts | UL | 0 | 2 | None |
| downlink-alerts | DL | 1e9 | 2 | One per DL/UL metric |
| downlink-no-alerts | DL | 0 | 2 | None |

Each case offers 1 Mbit/s UDP traffic for 30 seconds with 1200-byte
datagrams. The client binds to the UE address and oaitun_ue1.
The QoS xApp starts three seconds after the traffic process starts.
Its existing subscription demo observes reports for about ten seconds.

The high threshold deliberately forces the low-value condition for both
metrics, including the inactive traffic direction. Zero deliberately
prevents the low-value condition for nonnegative measurements.
These thresholds exercise logic; they are not operational SLA settings.

Checks include:
- Successful traffic exit, positive receiver bytes and bitrate.
- QoS process entirely inside the traffic subprocess window.
- Exactly one subscription to node 3584 and one deletion response.
- Both DL/UL metrics, at least three observations per metric,
  finite nonnegative means and positive sample counts.
- In alert cases, every observed mean below the test threshold,
  exactly one alert per metric, after precisely two observations.
- In no-alert cases, no alert messages.
- No callback errors, mismatched rows, unsupported formats, assertions,
  tracebacks, UNKNOWN or RECOVERY messages in these fixed-threshold cases.
- At least two positive active-direction means after excluding
  that metric's first observation.

The means parsed from logs are rounded to three decimal places.
The initial observation remains included in the actual xApp alert logic;
only the separate active-direction positive-count check excludes it.

Process-window containment does not prove exact alignment between
measurement intervals and packet transfer. The traffic process also
includes connection setup and completion.

## Observed results

Evidence directory:

/tmp/oai-dockerhub-qos-validation/oai-a4q2qujl

All cases subscribed to node 3584 and received one deletion response.

| Case | DL / UL observations | DL / UL alerts | Later positive active means | Receiver bit/s | Lost / total packets |
| --- | --- | --- | --- | --- | --- |
| uplink-alerts | 9 / 9 | 1 / 1 | 8 | 960576 | 0 / 3116 |
| uplink-no-alerts | 10 / 10 | 0 / 0 | 9 | 963372 | 7 / 3035 |
| downlink-alerts | 10 / 9 | 1 / 1 | 9 | 999975 | 0 / 3125 |
| downlink-no-alerts | 10 / 9 | 0 / 0 | 9 | 996125 | 9 / 3122 |

| Case | Receiver loss | Final receiver jitter, ms | First DL mean | First UL mean |
| --- | --- | --- | --- | --- |
| uplink-alerts | 0% | 5.168 | 9.616 | 7092.368 |
| uplink-no-alerts | 0.231% | 15.615 | 12.632 | 20670.384 |
| downlink-alerts | 0% | 5.326 | 6604.400 | 14641.952 |
| downlink-no-alerts | 0.287% | 10.754 | 21119.632 | 23.672 |

First means are in agent-reported units and include unusually high values.
They are preserved without asserting accuracy or equivalence to iperf.
Observation counts can vary; the validator does not require these exact
counts.

Evidence includes per-case QoS logs, iperf JSON and stderr logs,
image-pull.log, image-digests.json and summary.json.
The summary records process times, observation/alert counts,
initial means and receiver traffic results. Evidence remains outside Git.

The traffic client has a 45-second in-container timeout, plus a five-second
kill grace, and a 55-second host timeout. The xApp has a 60-second timeout.
Its uniquely named container is removed in cleanup.
The lab and traffic server require explicit cleanup.

## Cleanup

```bash
sudo docker stop oai-pi-oai-traffic
```

If the deadline has already removed it, confirm the server is absent.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue --profile tools down
```

The traffic server and RIC, gNB and UE containers were removed after
validation. External networks, subscriber credentials and the existing
core deployment were retained.

## Scope and remaining work

Validated: fixed-threshold alert and no-alert logic on OAI KPM data during
RFSim UE traffic, active-direction positive observations, absence of
repeated alerts in these cases and subscription cleanup.

This does not validate live degradation/recovery, missing-report timeout
detection, per-UE SLA enforcement, measurement accuracy or physical RF.
Recovery and missing-data state transitions remain covered by the
existing synthetic node-state regression tests, not by this experiment.
The causes of small UDP losses and high initial KPM values remain
unestablished. No scheduler changes or control actions are performed.
