# Experimental OAI dual-cell RFsim deployment

## Validation status

This is an experimental configuration, not a passed dual-cell workflow.
Experiments were performed on a four-core, approximately 8 GiB ARM64
Raspberry Pi on 2026-10-10.

Both gNBs completed NG, F1 and E2 setup. Each gNB/UE pair separately
established a session and reached the UPF in the 106 PRB experiments.
Concurrent attempts at 106 PRB and 24 PRB failed with growing UE RRC
queues and a Msg3 assertion. One DL actor and one UL actor per UE did
not resolve the failure.

Resource contention remains a hypothesis; the root cause is not isolated.
Simultaneous two-UE traffic, multi-cell load measurement and handover
are unvalidated. The current files retain the final 24 PRB experiment.

These are two independent RFsim gNB/UE links. A neighbour list does not
establish a shared RF channel, Xn connectivity or UE handover.

## Topology and prerequisites

| Component | RFsim lab address | Core address | Node / PCI |
| --- | --- | --- | --- |
| RIC | 172.29.0.10 | — | — |
| gNB 1 | 172.29.0.30 | 172.22.0.150 | 3584 / 0 |
| gNB 2 | 172.29.0.31 | 172.22.0.152 | 2816 / 1 |

Both cells use SSB ARFCN 640320, Point A 640032, 24 PRB, numerology 1
and min_rxtxtime 6. UE arguments use frequency 3604800000 and SSB offset 24.
The default RAN CPU set is 1-3; both pairs share those CPUs.

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
  -f deploy/oai-flexric/compose.oai-multi-cell.yaml)
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
usage and queue growth. This traffic phase has not passed in this lab.

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
tracks remaining work. Retry stable dual-cell sessions on a suitable host
or a documented distributed setup before claiming multi-cell load validation.
Any scheduling adjustment requires a new experiment. Do not bypass the
Msg3 assertion to mark the test as passed.
