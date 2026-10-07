# OAI RFSim UE to Open5GS end-to-end test

This workflow extends README.oai.md with a separate OAI NR UE container.
The gNB contains its E2 agent; the RIC and invoked xApps remain separate.

Run commands from the project root.

## Validated components

- OAI gNB: limx59/oai-gnb:arm64.
- OAI NR UE: limx59/oai-nr-ue:arm64.
- RIC and xApps: limx59/flexric-ric:arm64 and limx59/flexric-xapp:arm64.
- Existing Open5GS core on docker_open5gs_default.
- E2AP V2, KPM V3.00, PLMN 001/01, TAC 1.
- DNN internet, SST 1 without SD.

The UE connects only to the lab network. Its RFSim server is the gNB at
172.29.0.30:4043. User traffic enters oaitun_ue1 and crosses RFSim, the gNB
and Open5GS UPF.

The validated UE address was 192.168.100.245; allocation may differ later.
UPF ogstun was 192.168.100.1/24, with N3 address 172.22.0.8.

## Subscriber and local credentials

Provision a dedicated test subscriber in Open5GS, using an IMSI different
from active UERANSIM subscribers. This test used 001011234567896.

The preparation helper reads an existing subscriber from MongoDB. It does
not create or modify subscribers. It supports stored OPc, or derives OPc
from K and OP. Its session settings are fixed to internet and SST 1 without
SD; the subscriber and core must match those settings.

```bash
python3 deploy/oai-flexric/prepare-ue-config.py --imsi 001011234567896
```

The helper creates config/oai/ue.conf with mode 0600 and refuses to overwrite
it. The file is ignored by Git and must remain local. No credentials are
included in the published image.

OAI may print authentication keys in its runtime logs. Use selected event
lines when sharing or archiving logs.

## CPU and radio timing

The gNB sets min_rxtxtime to 6, matching OAI's RFSim examples. Without this
setting, the UE aborted because HARQ feedback time 2 was below its required
processing duration 3.

The Compose file restricts gNB and UE to CPUs 1-3 by default, leaving CPU 0
available to the core and host. Override OAI_RAN_CPUSET on other machines;
the selected CPU IDs must exist.

During the initial unrestricted run, multiple core services lost NRF
heartbeats and the AMF timed out on an SBI request. A subsequent request
failed because SCP attempted to reach UDM on port 80, although its configured
and NRF-advertised port was 7777. After CPU restriction and an AUSF restart,
UE registration and session establishment succeeded. This sequence suggests
resource contention and stale discovery state; it does not isolate a single
root cause.

Restarting AUSF is a troubleshooting action, not a routine deployment step.

## Build or pull

Both image and build settings are retained in Compose.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue build nrue
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue --profile tools pull ric gnb nrue xapp-nodes
```

The NR UE target reuses the gNB builder stage. A fresh build also compiles
the gNB; the validated cached UE build took approximately two minutes.

Published UE image-index digest:

sha256:230909b7e83f0fecd3ea1cca43d8d3e7b2834858da52367dfcb18f2f396af738

The UE image was built, runtime-tested, pushed and successfully pulled.
The end-to-end runtime test used the local build before publication.

## Start and inspect

Stop the emulator deployment first; it shares the static RIC address.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  up -d --no-build ric gnb
```

Confirm NG Setup and E2 Setup before starting the UE:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color gnb | \
  grep -E 'NGSetupResponse|associated AMF|E2 SETUP RESPONSE'
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue up -d --no-build nrue
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color nrue | \
  grep -iE '\[NAS\]|TUN Interface|PDU.session|Assertion'
```

Expected events include Registration Accept, PDU Session Establishment
Accept and successful configuration of oaitun_ue1.

## Connectivity

Explicitly bind traffic to the UE TUN interface. The container's default
route remains on its Docker network.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ping -I oaitun_ue1 -c 5 -W 5 192.168.100.1
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue ping -I oaitun_ue1 -c 5 -W 5 1.1.1.1
```

## Independent traffic server and UDP tests

Confirm 172.22.0.151 is available before starting the server:

```bash
sudo docker run -d --rm --name oai-pi-oai-traffic \
  --network docker_open5gs_default --ip 172.22.0.151 \
  --cap-add NET_ADMIN --entrypoint sh limx59/oai-nr-ue:arm64 \
  -c 'ip route add 192.168.100.0/24 via 172.22.0.8 &&
      exec timeout --signal=INT --kill-after=5s 900s \
      iperf3 -s -B 172.22.0.151'
```

Replace the bound UE address below if allocation differs.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  exec -T nrue timeout 45s iperf3 -c 172.22.0.151 \
  -B 192.168.100.245 --bind-dev oaitun_ue1 \
  -u -b 1M -l 1200 -t 10 -i 2
```

Repeat with -R for downlink.

For KPM observation, run a 25-second traffic test in one terminal and the
following xApp in another while traffic is active:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile tools run --rm --no-deps xapp-kpm
```

## Observed results

| Test | Result |
| --- | --- |
| UE registration and PDU session | Accepted; UE address 192.168.100.245 |
| Ping to UPF, 5 packets | 0% loss; average RTT 128.259 ms |
| Ping to 1.1.1.1, 5 packets | 0% loss; average RTT 267.155 ms |
| UDP uplink, 1 Mbit/s offered, 10 seconds | Receiver 952 Kbit/s; 0/1044 lost |
| UDP downlink, 1 Mbit/s offered, 10 seconds | Receiver 998 Kbit/s; 0/1040 lost |
| KPM during separate UL and DL traffic tests | UE reports received for node 3584 |
| KPM cleanup | Subscription delete responses received |

The first KPM indication in both tests was unusually high. Later indications
tracked the active traffic direction. Treat the initial sample separately;
this test does not establish measurement accuracy or maximum throughput.

These are short functional tests, not capacity, latency or endurance
benchmarks. Physical radios, ReDroid traffic integration, actual handover,
RC control compatibility and energy savings remain unvalidated.

## Stop

```bash
sudo docker stop oai-pi-oai-traffic
```

The traffic server removes itself on exit and has a 900-second deadline.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile ue down
```

The dedicated subscriber, local UE configuration, external networks and
existing core deployment remain available for future tests.
