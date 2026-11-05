# Multi-Agent slicing control: Compose dual-node coordination

## Status and scope

Passed on ARM64 Raspberry Pi within the bounded laboratory scope below.
The parent test-case name remains **Multi-Agent slicing control**.

Two OCUDU gNBs, each with one OAI ZMQ UE and SST 1 without SD, share an
Open5GS core. Two independent node Agent containers report actual
grant-conditioned DL queue samples. A central coordinator container evaluates
reports and maintains committed policy state. Control uses the cell-level
WebSocket interface; E2 is disabled.

This is an experimental common-cap policy, not a throughput optimization.
Each cell applies its own percentage independently; PRBs are not transferred
between cells.

## Policy and evidence

- Queue bytes are sampled after PDSCH transport-block construction.
- A missing grant is `unknown`, not evidence of an empty queue.
- Both reports must be valid and fresh at the coordinator's consumption time.
  The seven-second limit concerns host log-query receipt, not source collection.
- Two consecutive fresh pairs confirm a recommendation.
- Either node at or above 32 KiB recommends a 20% cap for both cells.
- Both nodes at or below 1 KiB recommend restoration to 100%.
- Unknown or middle-band pairs hold and reset confirmation.
- A 51-PRB cell has a limited maximum of 10 PRBs in this experiment.
- Both node callbacks must verify control response, connectivity, scheduler
  update and actual per-slot DL grants before the coordinator commits.
- Repeated confirmed state produces no additional control requests.

The TCP burst triggers queue observations. Separate 1200-byte control-phase
ping probes exercise the scheduler after each update. Lightweight probes
continue during report collection. These are distinct test stimuli.

## Compose execution

The external validator creates private configurations and exchange directories,
checks image platforms and addresses, and starts services with
`docker compose up -d --no-deps --no-build --pull never`.

Compose files:

- `../../deploy/ocudu/compose.slice-coordination.yaml`
- `../../deploy/ocudu/compose.slice-coordination-cpu.yaml`
- `../../deploy/ocudu/compose.slice-coordination-load.yaml`
- `../../deploy/ocudu/compose.slice-coordination-agents.yaml`

Agent and coordinator services exchange numbered JSON files through private
bind-mounted directories. They do not depend on attached terminal stdin.
The coordinator has no Docker socket. Agents access the host Docker API to
inspect their gNB processes and logs; a read-only socket bind does not enforce
read-only Docker API permissions.

Services use the host UID/GID for evidence files. Agent services additionally
receive the Docker socket group. The validator checks baseline continuity,
component exit codes and project-scoped cleanup.

Run from the existing configured laboratory:

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/validate-slice-coordination-compose.py" \
  --load-node 421
```

Swap the TCP load source:

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/validate-slice-coordination-compose.py" \
  --load-node 420
```

The validator prints a compact summary and retains full private evidence under
`test/ocudu/.local/evidence/`. Do not commit private configurations or raw logs.

## Images and builds

Runtime Agent/coordinator references use Docker Hub tags:

| Component | Image |
| --- | --- |
| Node Agent | `limx59/oai-pi-ocudu-slice-node-agent:arm64-queue-observation-test` |
| Coordinator | `limx59/oai-pi-ocudu-slice-coordinator:arm64-queue-control-test` |

Actual image IDs are retained in evidence for traceability.

```bash
sudo docker compose \
  -f "$HOME/Work/oai-5gc-pi-review/deploy/ocudu/compose.slice-coordination-build.yaml" \
  build node-agent coordinator
```

## Validation results

| Run | TCP load node | Result |
| --- | --- | --- |
| `bcf56fc8` | 421 | Compose closed loop passed |
| `o6ab802h` | 420 | Compose closed loop passed |
| `kjdzfaky` | 421 | Published-tag Compose closed loop passed |

Each run completed five report pairs, four validated control responses,
limitation and restoration, repeated-state suppression, component exit checks
and cleanup. Independent review recomputes DL grants and replays decisions.
Six in-memory mutations per run were rejected: cap exceedance, missing
restoration, missing scheduler update, stale report, missing peer and duplicate
control execution.

Evidence review:

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/validate-slice-closed-loop-evidence.py" \
  --evidence /absolute/path/to/retained/run
```

Separate fixture-driven testing demonstrated an isolated pre-send client
connection refusal, blocking of new plans, same-plan reconciliation and
restoration. That result does not establish container restart recovery or
ambiguous post-send failure recovery.

## Boundaries

This experiment does not validate E2/FlexRIC slice-control execution, peer
consensus, policy conflict arbitration, atomic cross-node updates, persistent
restart recovery, multi-UE/multi-slice competition, UL coordination effects,
sustained-load performance, physical RF or power savings.

Queue observations are grant-conditioned and do not establish PRB demand
percentages, continuous queue occupancy or source collection timestamps.
