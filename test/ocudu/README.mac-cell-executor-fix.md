# OCUDU MAC cell executor regression

## Scope and fix

This regression covers one OAI UE connected to an OCUDU gNB over ZMQ
on Raspberry Pi ARM64.

With one `main_pool` worker, GDB captured `mac_cell_processor::start()`
waiting in `sync_task_executor::defer()`. The startup coroutine and the
target MAC cell strand used the same worker pool. The patch makes MAC
cell control submissions asynchronous on the existing cell strand and
preserves synchronous ZMQ slot indication handling.

## Run the regression

Use the existing Open5GS test network and OCUDU ZMQ UE configuration.
Run these commands from the repository root.

```bash
sudo docker compose -f deploy/ocudu/compose.phy-concurrency-diag.yaml pull gnb
python3 -B test/ocudu/validate-mac-cell-executor-fix.py
```

The [diagnostic Compose file](../../deploy/ocudu/compose.phy-concurrency-diag.yaml)
selects the ARM64 gNB repair image. The Python entry point runs the one-worker
case followed by the two-worker case. Both use a 20-second UE tunnel readiness
window and a DU-low PHY concurrency limit of two. Each case must establish
the UE tunnel, pass both UPF probes, and complete cleanup without errors.

## Validation results

| Main-pool workers | UPF probes | Observed duration | Evidence directory |
| ---: | ---: | ---: | --- |
| 1 | 2/2 | 65.32 s | `ocudu-session-stability-2rirjc7f` |
| 2 | 2/2 | 65.33 s | `ocudu-session-stability-by_mpz4d` |

The functional runs used the locally built repair image. The ARM64 image
pulled from Docker Hub matched the tested local image ID. The evidence
directories are under `test/ocudu/.local/evidence/`.

## Build locally

```bash
sudo docker build --build-arg BUILD_JOBS=2 \
  --build-arg DIAG_PHY_CONCURRENCY=2 \
  -f docker/ocudu/Dockerfile.mac-cell-executor-fix \
  -t oai-pi-ocudu-gnb:arm64-mac-cell-executor-fix .
```

The Docker build applies the [MAC cell executor patch](patches/patch-ocudu-mac-cell-executor.py)
to its OCUDU source copy.
