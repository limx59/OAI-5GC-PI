# OCUDU + OAI UE bounded UDP validation

## Purpose

Validate receiver-side uplink and downlink UDP throughput and packet loss
through OAI UE, ZeroMQ, OCUDU gNB and the existing Open5GS UPF.
This is research-plan P5 and a prerequisite for later KPM load-response tests.

See the [integration guide and test matrix](README.md) for the topology,
source policy and overall progress.

## Environment

Validated on 2026-10-14, Pacific time, on a four-core Cortex-A76 ARM64
Raspberry Pi with approximately 8 GiB RAM.

- Existing Open5GS on `docker_open5gs_default`.
- OCUDU two-worker gNB at 172.22.0.160, CPU set 1-2.
- OAI UE at 172.22.0.161, CPU set 3.
- Dedicated temporary traffic endpoint at 172.22.0.151.
- UE subnet 192.168.100.0/24 routed via UPF 172.22.0.8 inside
  the traffic container only.
- iperf3 3.16; UDP offered load 1 Mbps; 1200-byte datagrams;
  10 seconds per direction, run sequentially.

CPU sets do not reserve exclusive host cores.

## Requirements

- Complete the private UE setup in the [integration guide](README.md).
- Keep subscriber credentials untracked; do not print or archive them.
- Existing core services and the external network must be running.
- Addresses .160, .161 and .151 must be available for this experiment.
- Both published images must already be present locally.
- No experiment RAN may be running; the named traffic container must not exist.
- Run commands from the repository root with working sudo Docker access.
- Keep `validate-zmq-connectivity.py` beside `validate-zmq-udp.py`;
  the UDP validator imports its command, state and address helpers.

## Images

| Component | Image |
| --- | --- |
| OAI UE and temporary traffic endpoint | `limx59/oai-pi-oai-nr-ue:arm64-zmq-test` |
| OCUDU two-worker gNB | `limx59/oai-pi-ocudu-gnb:arm64-zmq-worker-test` |

Published image-index digests:

- OAI UE: `sha256:73fa22bcb85f2c040a398d0c3159a7a9083e7dee7db23a7c6fe7e3c26d2110e8`
- OCUDU gNB: `sha256:1733f139f5e1001ca0c146f8b51e017d9fe71b0c07616beff233b468be8cc608`

The validator uses both OCUDU Compose files and never builds or pulls images.

## Steps

The validator starts the experiment itself. Do not start containers manually.

Single round:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 test/ocudu/validate-zmq-udp.py \
  --rounds 1 --output-dir /tmp/ocudu-zmq-udp </dev/null
```

Three fresh-container rounds:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 test/ocudu/validate-zmq-udp.py \
  --rounds 3 --output-dir /tmp/ocudu-zmq-udp-regression </dev/null
```

Each round creates the traffic server with a 300-second timeout,
recreates gNB/UE, waits for the UE TUN IPv4 address, checks five
traffic-endpoint pings, runs UL/DL traffic, repeats the five pings,
and checks sampled process identities and UE address stability.

## Validation

Acceptance requires all of the following:

- Receiver throughput at least 800000 bit/s (80% of offered load).
- Packet loss no greater than 5%; positive received bytes.
- Successful iperf execution without a JSON error.
- Five out of five ping replies before and after traffic.
- Unchanged sampled container ID, image ID, PID, start time, restart
  count and UE IPv4 address.
- Successful RAN stopping and temporary traffic-container removal.

Failures retain evidence and stop the remaining rounds.
Do not silently relax acceptance thresholds.

Single automated round: UL 994354 bit/s, DL 1000234 bit/s;
both directions had 0% loss and cleanup passed.

Three-round results:

| Round | UL received (bit/s) | DL received (bit/s) | UL / DL loss | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | 994697 | 1001203 | 0% / 0% | Passed |
| 2 | 993786 | 999323 | 0% / 0% | Passed |
| 3 | 992856 | 1001204 | 0% / 0% | Passed |

## Evidence

- Single round: `/tmp/ocudu-zmq-udp/run-gsia0tk6`
- Three rounds: `/tmp/ocudu-zmq-udp-regression/run-5zqkeyp6`
- Checked archive under `~/Work/oai-test-evidence/`:
  `ocudu-oai-zmq-udp-regression-20261014-232215.tar.gz`

Each round retains iperf JSON in `uplink.stdout` / `downlink.stdout`,
including requested server output, separate stderr, ping results,
filtered RAN logs, startup/cleanup output and a run-level `summary.json`.

An earlier manual test passed both traffic directions, but its immediate
cleanup check saw the auto-removing server before deletion completed.
A subsequent check confirmed removal. The automated validator instead
explicitly removes the server and polls for absence; all documented
automated rounds passed cleanup.

## Cleanup

The validator stops gNB/UE, retains their stopped containers for inspection,
and explicitly removes `oai-pi-ocudu-traffic`.
It preserves Open5GS, UERANSIM, ReDroid, shared networks and host settings.

Inspect remaining experiment containers:

```bash
sudo docker ps -a --filter 'name=^/oai-pi-ocudu-traffic$' \
  --format 'table {{.Names}}\t{{.Status}}'
sudo docker ps -a --filter 'name=^/oai-pi-ocudu-zmq-lab-' \
  --format 'table {{.Names}}\t{{.Status}}'
```

Expected: no traffic container; retained gNB/UE containers are stopped.
For removal of retained RAN containers, follow the integration guide.
Do not prune unrelated resources.

## Limitations

- Bounded 1 Mbps offered-load validation, not maximum capacity.
- Fresh-container rounds do not establish sustained-session stability.
- Sampled process/address checks do not prove uninterrupted RNTI,
  UE-context or PDU-session continuity.
- No physical RF, KPM measurement accuracy, E2 interoperability,
  QoS alerting or control-loop validation is established by this test.
- Exact single-worker blocking-path diagnosis remains open.
