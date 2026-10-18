# One-second DU KPM monitoring test

## 1. Prepare

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Prerequisites:

- Four-core Cortex-A76 ARM64 Raspberry Pi with approximately 8 GiB RAM.
- Existing Open5GS services and Docker network running.
- Subscriber and private UE configuration already provisioned.
- Existing OCUDU FlexRIC RIC container running.
- UE and xApp images from [the KPM guide](README.zmq-kpm.md) available locally.
- Address 172.22.0.151 available for the temporary traffic endpoint.
- No competing full RAN experiment running.

Pull the deployment image:

```bash
sudo docker pull limx59/oai-pi-ocudu-gnb@sha256:bff13777799f436cb3abdfa9e5433fd7f306c8d8898c69b26b9e664b4160b844
```

## 2. Start gNB and UE

```bash
sudo docker compose \
  -f deploy/ocudu/compose.zmq.yaml \
  -f deploy/ocudu/compose.zmq-worker-test.yaml \
  -f deploy/ocudu/compose.e2.yaml \
  -f test/ocudu/patches/compose.kpm-collection-clock.yaml \
  --profile ue up -d --no-deps --force-recreate --no-build --pull never gnb nrue
```

The override selects the pinned image, enables independent reporting and RLC
metrics clocks, and sets gNB CPUs to 0-2 and UE CPU to 3.

Check registration:

```bash
sudo docker logs --timestamps \
  --since "$(sudo docker inspect --format '{{.State.StartedAt}}' oai-pi-ocudu-zmq-lab-nrue-1)" \
  --tail 150 oai-pi-ocudu-zmq-lab-nrue-1 2>&1 |
  grep -Ei 'Registration|PDU.session|oaitun|reject|assert|exiting|Bye\.' |
  sed -E '/UICC|IMSI|IMEI|K_int|K_enc|K_gNB|KgNB|K_AMF|KAMF|secret|password/Id; s/[0-9]{10,}/[REDACTED]/g'
```

Require Registration Accept, PDU Session Establishment Accept and a configured
oaitun_ue1 interface. Stop testing if registration fails; do not automatically
restart shared core services.

Check connectivity:

```bash
sudo docker exec oai-pi-ocudu-zmq-lab-nrue-1 \
  ping -I oaitun_ue1 -c 5 -W 2 192.168.100.1
```

Require five replies.

## 3. Run three idle rounds

```bash
python3 - <<'IDLE'
from pathlib import Path
import subprocess
import sys

script = Path("test/ocudu/validate-zmq-kpm-timing.py")
for number in range(1, 4):
    print(f"\n=== Idle round {number}/3 ===", flush=True)
    subprocess.run([
        sys.executable, "-B", str(script),
        "--gnb-cpus", "0-2", "--ue-cpus", "3", "--seconds", "60",
    ], check=True, stdin=subprocess.DEVNULL)
IDLE
```

For every round, inspect the printed interval statistics and retained CSV.

Require:

- At least 58 report timestamps during the 60-second recording.
- One DL and one UL numeric measurement per report.
- No no_value records or incomplete measurements.
- Median receive interval between 0.95 and 1.05 seconds.
- All receive intervals between 0.8 and 1.2 seconds.
- Passing before/after tunnel pings, stable container identities and normal deletion.

The idle script reports measurements but does not enforce the timing thresholds
above. Its summary labels timing acceptance as unevaluated; review the observed
statistics separately.

## 4. Run three traffic rounds

```bash
python3 - <<'TRAFFIC'
from pathlib import Path
import subprocess
import sys

script = Path("test/ocudu/validate-kpm-current-traffic.py")
for number in range(1, 4):
    print(f"\n=== Traffic round {number}/3 ===", flush=True)
    subprocess.run([
        sys.executable, "-B", str(script),
    ], check=True, stdin=subprocess.DEVNULL)
print("PASS: three traffic rounds.")
TRAFFIC
```

Each round sends 1 Mbps UDP for 10 seconds per direction with KPM recording.
The script checks:

- Receiver throughput at least 800,000 bit/s and packet loss no greater than 5%.
- Finite, nonnegative numeric DL/UL records without missing values.
- At least two later positive reports for the loaded direction.
- At least seven reports during each traffic phase.
- Median receive interval between 0.95 and 1.05 seconds.
- All receive intervals between 0.8 and 1.2 seconds.
- Normal subscription deletion and post-deletion observation.
- Stable gNB, UE and RIC identities and unchanged UE tunnel address.

Temporary recorder and traffic containers are removed automatically.
The current gNB, UE, RIC and shared core remain running.

## 5. Retain evidence

Each script prints its evidence directory under:

```text
~/Work/oai-test-evidence/
```

Retain summary.json, CSV, traffic JSON, recorder logs and cleanup logs.
Keep evidence outside Git, including failed runs.

These tests cover single-UE ZeroMQ receive cadence and bounded load response.
They do not establish exact measurement age, metric accuracy, physical RF
performance or long-term stability.

## 6. Stop gNB and UE

```bash
sudo docker compose \
  -f deploy/ocudu/compose.zmq.yaml \
  -f deploy/ocudu/compose.zmq-worker-test.yaml \
  -f deploy/ocudu/compose.e2.yaml \
  -f test/ocudu/patches/compose.kpm-collection-clock.yaml \
  --profile ue stop nrue gnb
```

Retain shared Open5GS, UERANSIM, redroid and RIC services.
