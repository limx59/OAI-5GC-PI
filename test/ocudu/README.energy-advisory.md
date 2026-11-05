# Energy-saving control: advisory and state simulation

## Status and scope

Passed within the explicit synthetic-input advisory and simulated-feedback
scope. The parent test-case name remains **Energy-saving control**.

The Compose service reuses `test/xapp/xapp_energy_policy.py` and
`test/xapp/xapp_energy_simulator.py`. No OCUDU gNB, UE or RIC is started.
Demand ratio, active UE count, neighbor coverage and sample time come from
supplied fixtures; they are not live RAN measurements.

The simulator changes only an in-memory mode. Every result retains
`executed: false`, `real_control_executed: false` and
`power_saving_measured: false`.

## Policy

- Demand at or below 0.2, zero active UEs and confirmed neighbor coverage
  must persist for 30 simulated seconds before suggesting energy saving.
- A sample gap greater than 15 simulated seconds resets confirmation.
- In energy-saving mode, demand at or above 0.6, an active UE or loss of
  coverage confirmation recommends restoration.
- The default six-observation fixture suggests entry at time 30 and
  restoration at time 50. These are simulated times, not elapsed test duration.

## Image and Compose execution

Image: `limx59/oai-pi-ocudu-energy-advisor:arm64-state-simulation-test`.

The service uses a read-only filesystem, host UID/GID, no network, no Docker
socket and no added capabilities. Input is mounted read-only and results are
written into a private evidence directory.

Run the external validator:

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/validate-energy-advisory-compose.py"
```

The validator creates a private input snapshot and environment file, checks
Compose isolation and ARM64 image identity, starts the service with
`docker compose up -d --no-deps --no-build --pull never`, checks its exit,
performs project cleanup and verifies baseline process continuity.
It then independently reviews the saved evidence.

The build definition is `../../docker/ocudu/Dockerfile.energy-advisor`;
the Compose service is `../../deploy/ocudu/compose.energy-advisory.yaml`.
The image includes the external Python source files. Runtime references use
tags; actual image IDs are retained for traceability.

## Evidence and checks

Evidence remains under `test/ocudu/.local/evidence/`:

- `input.json`: immutable-for-the-run input snapshot.
- `results/advisory.jsonl`: policy recommendations without state execution.
- `results/simulation.jsonl`: simulated mode feedback and transitions.
- `results/summary.json`: input hash, scope and result summary.
- `summary.json`: container outcome, image identity and baseline/cleanup checks.
- `independent-review.json`: independent record-level validation.

Seven offline policy checks passed, including low-demand duration, blocking
conditions, gap reset, restoration triggers and invalid observations.
Compose runs `mo2fmgu6` and `wj11kq1a` passed; the latter used the reusable
validator with input snapshots and baseline continuity checks.

Run retained-evidence and negative checks:

```bash
python3 -B "$HOME/Work/oai-5gc-pi-review/test/ocudu/validate-energy-evidence.py" \
  --evidence /absolute/path/to/retained/run
```

Six in-memory mutations are rejected: wrong recommendation, wrong transition,
broken state continuity, duplicate sequence, false real-control claim and
false power-measurement claim. Original evidence is not modified.

The Docker Hub tag was pushed and pulled successfully with an image identity
matching the validated build. No additional post-pull execution was required
because the image content was unchanged.

## Remaining scope

Live OCUDU metric ingestion and measured neighbor coverage are unvalidated.
Physical-device control and power measurement remain deferred pending
hardware. This simulation does not establish actual sleep/wake operation,
service continuity during physical mode changes or measured energy savings.

Private evidence and generated configuration files must not be committed.
