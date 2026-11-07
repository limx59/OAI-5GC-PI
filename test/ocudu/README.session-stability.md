# Bounded single-UE session stability

## Scope and results

Validated through Docker Compose on a four-core Cortex-A76 ARM64
Raspberry Pi with approximately 8 GiB RAM. The first two runs used the
v1 runner on 2026-11-04 Pacific time. The 24-hour run used the v2 runner.

| Requested duration | Probe interval | Observed duration | UE IPv4 | Passed probes | Ping replies | Evidence directory |
| --- | --- | --- | --- | --- | --- | --- |
| 60 s | 15 s | 65.86 s | 192.168.100.22 | 5/5 | 25/25 | `ocudu-session-stability-cq_kq636` |
| 300 s | 30 s | 306.05 s | 192.168.100.23 | 11/11 | 55/55 | `ocudu-session-stability-iolfzmg2` |
| 86,400 s | 30 s | 86,405.56 s | 192.168.100.28 | 2,805/2,805 | 14,025/14,025 | `ocudu-session-stability-jny2xi60` |

All passing runs completed the sampled test-process identity and UE tunnel-address
checks, mounted-input hash checks, baseline container continuity checks
and automatic cleanup. Final probes and checks extend execution beyond
the requested duration.

Each run started a fresh session. The 24-hour run validates sampled
single-UE ZMQ session retention and periodic UPF connectivity. Connectivity
between probes, sustained application traffic, multi-UE operation, physical
RF and full workflow regression are outside this test's scope.

The first 24-hour attempt stopped when probe 2,521 received four of five
replies. Its last passing probe was at 77,669.2 seconds. The v2 runner
passed a 60-second preflight and a separate failure-path check before the
successful 24-hour run. The failure-path check injected a first-probe 4/5
result, triggered a real diagnostic retry, returned exit code 1 and reported
no cleanup errors.

## Components

| Component | Image |
| --- | --- |
| Test runner | `limx59/oai-pi-ocudu-session-test:arm64-session-stability-v2-test` |
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

### 24-hour validation

At the validated checkout path, pull the published runner. For a different
checkout path, follow the local build procedure above and skip the pull.

```bash
export OCUDU_SESSION_ROOT="$(pwd -P)"

sudo --preserve-env=OCUDU_SESSION_ROOT docker compose \
  -p ocudu-session-runner-v2 \
  -f deploy/ocudu/compose.session-stability-runner.yaml \
  pull session-test

run_name="ocudu-session-stability-v2-24h-$(date +%Y%m%d-%H%M%S)"
sudo --preserve-env=OCUDU_SESSION_ROOT docker compose \
  -p ocudu-session-runner-v2 \
  -f deploy/ocudu/compose.session-stability-runner.yaml \
  run -d --name "$run_name" --no-deps --pull never session-test \
  --duration-seconds 86400 --interval-seconds 30

sudo docker logs -f --tail 20 "$run_name"
sudo docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' "$run_name"
```

Runtime does not build or pull gNB/UE images. The validator waits for
`oaitun_ue1` IPv4 readiness, then sends five TUN-bound pings to
192.168.100.1 per probe. Each probe requires five replies and zero loss.
Probe timing includes Docker and validation overhead. A failed initial
probe triggers one diagnostic retry, saved as `ping.NNNNNN.retry.log`.
The initial 5/5 acceptance rule still determines the result.

## Evidence and cleanup

Evidence remains in `test/ocudu/.local/evidence/`.
The runner and host use the same absolute evidence path so sibling
gNB bind mounts resolve on the host Docker daemon.

Retained files include generated configuration, `resolved-compose.json`,
`startup.log`, `samples.jsonl`, per-probe ping logs, final gNB/UE logs,
`cleanup.log` and `summary.json`.

The v2 validator collects the last 2,000 log lines per gNB/UE container
and removes its independent RAN project on normal success and handled
failures. The short checks use `--rm`. The detached 24-hour command retains
the runner container for exit-status inspection.
A forced runner termination can bypass cleanup; inspect the exact
experiment project before removing leftovers. Do not prune shared
Open5GS services, unrelated containers or networks.

Keep `.local/`, credentials and raw logs untracked. UE logs may include
subscriber credentials.

## Published runner images

| Runner | Docker Hub image-index digest |
| --- | --- |
| v2 (`arm64-session-stability-v2-test`) | `sha256:c2d9adcd9e7fe022ecc88346f6d89bc712ad01cdb624228cec0a1ab8cea59430` |
| v1 (`arm64-session-stability-test`, historical) | `sha256:d570e76b4c7860bc793c43eda669ddd1d0ad46eb7002dffecc56ff05d3696ed6` |

The successful 24-hour run used the locally built v2 runner. After
publication, the pulled `linux/arm64` image ID matched the image ID of
the successful runner container. Registry verification checked image
identity only.
