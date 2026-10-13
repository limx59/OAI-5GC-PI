# Experimental OAI dual-cell RFsim deployment

## Validation status

Bounded concurrent dual-cell RFsim traffic and per-node MAC measurements
passed on the four-core, approximately 8 GiB ARM64 Raspberry Pi on
2026-10-12, Pacific time.

The successful configuration uses 24 PRB, one DL and one UL actor per UE,
and separate container CPU placement: gNB 1=1, UE 1=2, gNB 2=3, UE 2=0.
These CPU sets do not reserve exclusive host cores. Other services retain
their existing configuration.

Both UEs established distinct PDU-session IPv4 addresses and passed
concurrent UPF pings. Four traffic phases passed: concurrent UDP uplink
and downlink, each with 1 Mbps and 200 kbps offered rates, then exchanging
the high-rate UE. Actual MAC byte/PRB counter rates followed the exchanged
load. Five process identities and both UE addresses remained unchanged.

The dedicated 100 ms MAC collector passed three local-image regression
rounds, covering 12 phases. A later published-image sequence passed its
first round but failed in the second: UE 1 experienced PUSCH DTX, UL
failure, RRC reestablishment and residual UE contexts; UE 2 had excessive
packet loss. This failure remains part of the evidence.

After experiment cleanup and fresh topology creation, one four-phase
validation and three consecutive regression rounds passed using the
published-image default. All 12 phases passed with the same five
processes and both UE addresses throughout the three rounds.

Earlier concurrent attempts on 2026-10-10 failed with UE RRC queue growth
and a Msg3 assertion at both 106 and 24 PRB. Those failures are retained;
the root cause of either failure sequence has not been isolated.

These are two independent RFsim gNB/UE links. A neighbour list does not
establish a shared RF channel, Xn connectivity or UE handover.
MAC byte/PRB rates are not normalized cell utilization or capacity.
This experiment does not establish physical RF or long-term reliability.

## Topology and prerequisites

| Component | RFsim lab address | Core address | Node / PCI |
| --- | --- | --- | --- |
| RIC | 172.29.0.10 | — | — |
| gNB 1 | 172.29.0.30 | 172.22.0.150 | 3584 / 0 |
| gNB 2 | 172.29.0.31 | 172.22.0.152 | 2816 / 1 |

Both cells use SSB ARFCN 640320, Point A 640032, 24 PRB, numerology 1
and min_rxtxtime 6. UE arguments use frequency 3604800000 and SSB offset 24.
Without the dedicated CPU overlay, both pairs share CPUs 1-3.
Use the CPU overlay below for the measured 2026-10-12 experiment.

Requirements:

- Docker Compose, Python 3, sudo, SCTP and TUN support.
- Compatible ARM64 images already available locally.
- External networks oai-pi-flexric-lab (172.29.0.0/24) and
  docker_open5gs_default (172.22.0.0/24), without address conflicts.
- Existing Open5GS core, AMF 172.22.0.10 and UPF 172.22.0.8.
- Two distinct provisioned subscribers matching internet, SST 1, no SD.
- Local, Git-ignored UE configuration files.

See [the end-to-end guide](../../deploy/oai-flexric/README.e2e.md)
for core and subscriber preparation. The helper reads existing subscribers;
it does not provision them. Do not overwrite an existing UE configuration.

For this experiment, ue.conf uses subscriber 001011234567896 and server
172.29.0.30. The second subscriber is 001011234567897. After provisioning
that subscriber, generate its local configuration:

```bash
python3 deploy/oai-flexric/prepare-ue-config.py \
  --imsi 001011234567897 --output-name ue-2.conf \
  --rfsim-server 172.29.0.31
```

Keep both UE files local. Do not publish authentication keys or unrestricted
OAI runtime logs.

## Experimental reproduction

Run from the repository root. Define the complete Compose file set:

```bash
compose=(sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  -f deploy/oai-flexric/compose.oai-multi-cell.yaml \
  -f deploy/oai-flexric/compose.oai-multi-cell-cpu-isolated.yaml)
```

Validate the merged configuration:

```bash
"${compose[@]}" --profile ue --profile tools config --quiet
```

Start the RIC, then the two gNBs:

```bash
"${compose[@]}" up -d --no-build --pull never ric
"${compose[@]}" up -d --no-build --pull never --no-deps gnb gnb-2
```

Check both gNBs for NGSetupResponse, F1 Setup Response and E2 setup response
before starting the UEs. A running container alone is not a setup check.

```bash
"${compose[@]}" --profile ue up -d --no-build --pull never \
  --no-deps --force-recreate nrue nrue-2
```

Check each UE process and its oaitun_ue1 address. Registration Accept alone
does not prove PDU session establishment. Discover allocated UE addresses
at runtime; do not assume addresses from earlier runs.

```bash
"${compose[@]}" --profile ue exec -T nrue \
  ip -4 addr show dev oaitun_ue1
"${compose[@]}" --profile ue exec -T nrue-2 \
  ip -4 addr show dev oaitun_ue1
```

Only proceed to concurrent traffic after both sessions remain healthy.
Use independent iperf3 server ports or instances for concurrent clients.
Collect per-node MAC/KPM reports, traffic results, process health, CPU
usage and queue growth. The bounded traffic phases described below passed in this lab.

## Successful load validation workflow

Start the RIC and both gNBs, verify NG/F1/E2 setup, then start both UEs.
Verify distinct TUN addresses and concurrent 5/5 UPF pings before traffic.
The successful retry retained the original gNB worker configuration;
the separate single-worker overlay is not part of these passed results.

The collector image is:

- `limx59/oai-pi-flexric-xapp:arm64-oai-mac-100ms-test`
- Image-index digest:
  `sha256:00b7700a6fa6184033e73188240d138b61f5a678aa0e0f8a35e09294fbd5fea1`

```bash
sudo docker pull limx59/oai-pi-flexric-xapp:arm64-oai-mac-100ms-test
python3 test/flexric/validate-oai-multi-cell-load.py \
  --output-dir /tmp/oai-multi-cell-load-single </dev/null
```

After a successful single validation, keep the same topology and session:

```bash
python3 test/flexric/validate-oai-multi-cell-load-regression.py \
  --output-dir /tmp/oai-multi-cell-load-regression </dev/null
```

Both scripts default to the published 100 ms collector image. Each phase
automatically starts its collector container, subscribes to both nodes,
checks actual cumulative counters and normally deletes both subscriptions.
Do not manually start an additional collector.

The validator owns a temporary traffic server with independent ports 5201
and 5202 and a route added only inside that container. It checks received
rate of at least 80 percent of offered rate and packet loss no greater than
5 percent. MAC measurement windows must span at least ten seconds, have
stable RNTIs, increasing counters, report gaps and receive delays no greater
than two seconds. Per-node byte rates must rise by at least 20 percent when
that node changes from the low to the high offered rate.

The three-round wrapper requires unchanged five processes and two UE
addresses across rounds. Temporary traffic and collector containers are
removed; the RAN topology remains available for inspection.

The earlier 10 ms collector failed the two-second report-delay check.
With 100 ms collection, the initial successful four-phase run had zero
packet loss and a maximum measured-window report delay of about 0.284 s.
This reduces telemetry frequency; it does not relax the freshness threshold.

The dedicated patch `patches/prepare-oai-mac-100ms.py` modifies only the
Docker SDK/xApp copy. The tracked OAI/FlexRIC source trees and original
10 ms xApp remain unchanged. Build the dedicated collector with:

```bash
sudo docker build -f docker/flexric/Dockerfile.oai-mac-100ms \
  --target xapp --build-arg BUILD_JOBS=2 \
  -t oai-pi-flexric-xapp:oai-mac-100ms-test .
```

Selected evidence archives under `~/Work/oai-test-evidence/`:

- `oai-dual-cell-load-initial-20261012-213020.tar.gz`
- `oai-multi-cell-load-regression-20261012-214458-regression-d9sfkwf0.tar.gz`
- `oai-multi-cell-load-regression-20261012-220804-regression-te4upli8.tar.gz`
- `oai-multi-cell-published-failure-diagnostics-20261012-221041.tar.gz`

The last two archives record a failed sequence, not a passed regression.
Fresh single-run evidence:
`/tmp/oai-multi-cell-load-fresh-single/run-efnb0d2b`.

Passed fresh published-image three-round archive:
`oai-multi-cell-load-regression-20261012-223715-regression-nurnxmwz.tar.gz`.
Evidence directory:
`/tmp/oai-multi-cell-load-fresh-regression/regression-nurnxmwz`.

## Diagnostics and cleanup

On failure, stop the experimental RAN processes first. Stopped containers
retain their logs until removed or recreated.

```bash
"${compose[@]}" --profile ue stop --timeout 15 nrue nrue-2 gnb gnb-2
```

Save selected diagnostic events and process state before removing containers.
The experiment archives are local under ~/Work/oai-test-evidence/:

- oai-multi-cell-24prb-diagnostic-20261010-141308.tar.gz
- oai-multi-cell-actors-diagnostic-20261010-185550.tar.gz

Remove this OAI experiment project, including its RIC and temporary tools:

```bash
"${compose[@]}" --profile ue --profile tools down --remove-orphans
```

Verify that no project containers remain:

```bash
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-oai-e2-lab \
  --format 'table {{.Names}}\t{{.Status}}'
```

External networks, Open5GS, UERANSIM, redroid, subscribers, images and local
UE credentials are retained. Use this cleanup only when the OAI experiment
project has no other active work.

## Continuation

The original ten-case [test TODO](README.md#test-todo-and-validation-status)
tracks remaining work. Reproduce bounded dual-cell sessions and load measurements using the
documented CPU placement and 100 ms collector. Preserve failed runs and
retain the bounded scope when reporting the passed fresh published-image regression.
Any scheduling adjustment requires a new experiment. Do not bypass the
Msg3 assertion to mark the test as passed.
