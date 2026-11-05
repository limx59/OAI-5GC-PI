# Bounded single-UE session stability

## Scope and results

Validated through Docker Compose on a four-core Cortex-A76 ARM64
Raspberry Pi with approximately 8 GiB RAM on 2026-11-04, Pacific time.

| Requested duration | Probe interval | Observed duration | UE IPv4 | Passed probes | Ping replies | Evidence directory |
| --- | --- | --- | --- | --- | --- | --- |
| 60 s | 15 s | 65.86 s | 192.168.100.22 | 5/5 | 25/25 | `ocudu-session-stability-cq_kq636` |
| 300 s | 30 s | 306.05 s | 192.168.100.23 | 11/11 | 55/55 | `ocudu-session-stability-iolfzmg2` |

Both runs passed sampled test-process identity and UE tunnel-address
checks, mounted-input hash checks, baseline container continuity checks
and automatic cleanup. Final probes and checks extend execution beyond
the requested duration.

These are separate fresh-session runs, not three-round regression.
The checks establish bounded single-UE ZMQ session retention and periodic
UPF connectivity. They do not establish uninterrupted connectivity between
probes, continuous application traffic, long-term stability, multi-UE
behavior, physical RF or complete integrated-workflow regression.

## Components

| Component | Image |
| --- | --- |
| Test runner | `limx59/oai-pi-ocudu-session-test:arm64-session-stability-test` |
| gNB | `limx59/oai-pi-ocudu-gnb:arm64-steering-prb-kpm-metadata-v2-test` |
| OAI UE | `limx59/oai-pi-oai-nr-ue:arm64-zmq-dci10-config-selection-test` |

The runner packages `prepare-session-stability.py`,
`validate-session-stability.py`, the base gNB configuration and the RAN
Compose files. Preparation generates a private configuration with an
explicit two-worker main pool. The gNB mounts it read-only.

An earlier one-worker run failed UE initial synchronization. Adding the
explicit two-worker configuration restored attachment with the same
gNB/UE image tags. This does not establish the precise single-worker
root cause.

The runner calls the host Docker daemon through its mounted socket.
It creates an independent RAN Compose project and removes that project
after log collection. There is no Docker-in-Docker daemon.
Both Python scripts run inside the test runner.

## Prerequisites

- Existing Open5GS services and `docker_open5gs_default` network.
- Free experiment addresses 172.22.0.160 and 172.22.0.161.
- Existing local ARM64 gNB and UE images listed above.
- Matching subscriber provisioned in Open5GS.
- Private UE file `deploy/ocudu/.local/ue-zmq.conf`, retaining the
  provisioned subscriber/PDU settings and ZMQ endpoints.
- Capability XML at
  `oai/targets/PROJECTS/GENERIC-NR-5GC/CONF/uecap_ports1.xml`.
- Host `/dev/net/tun` and the existing `test/ocudu/.local/` directory.

The private UE file and capability XML are mounted read-only.
Subscriber configuration is excluded from the image build context.
Do not start gNB/UE separately or run competing tests on .160/.161.

## Build

Run from the repository root:

```bash
export OCUDU_SESSION_ROOT="$PWD"

sudo --preserve-env=OCUDU_SESSION_ROOT docker compose \
  -p ocudu-session-runner \
  -f deploy/ocudu/compose.session-stability-runner.yaml \
  build session-test
```

Dockerfile: `docker/ocudu/Dockerfile.session-stability`.
Its dedicated Docker ignore file allows only the required scripts,
public configuration and RAN Compose files.

Build and test execution are separate. The runner image embeds the
repository absolute path supplied at build time. Rebuild the runner
if the checkout path differs; the registry image alone is not portable
to arbitrary checkout paths. The validated path is
`/home/limx59/Work/oai-5gc-pi-review`.

## Run

```bash
export OCUDU_SESSION_ROOT="$PWD"

sudo --preserve-env=OCUDU_SESSION_ROOT docker compose \
  -p ocudu-session-runner \
  -f deploy/ocudu/compose.session-stability-runner.yaml \
  run --rm --no-deps --pull never session-test \
  --duration-seconds 60 \
  --interval-seconds 15
```

Five-minute check:

```bash
sudo --preserve-env=OCUDU_SESSION_ROOT docker compose \
  -p ocudu-session-runner \
  -f deploy/ocudu/compose.session-stability-runner.yaml \
  run --rm --no-deps --pull never session-test \
  --duration-seconds 300 \
  --interval-seconds 30
```

Runtime does not build or pull gNB/UE images. The validator waits for
`oaitun_ue1` IPv4 readiness, then sends five TUN-bound pings to
192.168.100.1 per probe. Each probe requires five replies and zero loss.
Probe timing includes Docker/check overhead and is not an exact timer.

## Evidence and cleanup

Evidence remains in `test/ocudu/.local/evidence/`.
The runner and host use the same absolute evidence path so sibling
gNB bind mounts resolve on the host Docker daemon.

Retained files include generated configuration, `resolved-compose.json`,
`startup.log`, `samples.jsonl`, per-probe ping logs, final gNB/UE logs,
`cleanup.log` and `summary.json`.

The validator collects logs and removes its independent RAN project
on normal success and handled failures. `--rm` removes the runner.
A forced runner termination can bypass cleanup; inspect the exact
experiment project before removing leftovers. Do not prune shared
Open5GS services, unrelated containers or networks.

Keep `.local/`, credentials and raw logs untracked. UE logs may include
subscriber credentials. The runner image was pushed to Docker Hub and pulled successfully.
The pulled image identity matched the locally tested image;
the platform was verified as `linux/arm64`.

Published image-index digest:

`sha256:d570e76b4c7860bc793c43eda669ddd1d0ad46eb7002dffecc56ff05d3696ed6`

The functional runs above used the locally built image. Registry
verification checked image identity; no separate post-pull run is claimed.
