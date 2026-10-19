# KPM subscription rejection test

## 1. Prepare

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

Prerequisites:

- Raspberry Pi 5 ARM64 with Docker and Docker Compose.
- Existing Open5GS services and docker_open5gs_default network.
- Provisioned private OAI UE configuration.
- Existing baseline OCUDU RIC running at 172.22.0.162.
- Address 172.22.0.163 available for the temporary test RIC.
- No concurrent OCUDU experiment or xApp test.

Pull the test images:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-ric:arm64-subscription-failures-test
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-subscription-failures-test
```

Ensure the gNB and UE images referenced by the existing Compose files are
available. Follow [the one-second monitoring guide](README.kpm-one-second.md)
for the RAN prerequisites.

Stop the experimental gNB and UE before running this validator:

```bash
sudo docker compose \
  -f deploy/ocudu/compose.zmq.yaml \
  -f deploy/ocudu/compose.zmq-worker-test.yaml \
  -f deploy/ocudu/compose.e2.yaml \
  -f test/ocudu/patches/compose.kpm-collection-clock.yaml \
  --profile ue stop nrue gnb
```

Keep the baseline RIC, Open5GS, UERANSIM and ReDroid running.

## 2. Run one round

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  test/ocudu/validate-kpm-subscription-rejection.py </dev/null
```

The validator creates a temporary RIC at 172.22.0.163 and starts the
experimental gNB and UE with a temporary E2 configuration.

The probe requests an unsupported metric, checks rejection, then requests
DRB.UEThpDl and DRB.UEThpUl in the same xApp process. It checks subsequent
reports and a normal subscription delete response.

At completion, the validator removes its temporary containers and restores
the original gNB/UE Compose configuration with both RAN containers stopped.
The baseline RIC remains running.

## 3. Repeat three rounds

```bash
python3 - <<'CHECK'
from pathlib import Path
import subprocess
import sys

script = Path("test/ocudu/validate-kpm-subscription-rejection.py")
for number in range(1, 4):
    print(f"\n=== Rejection/recovery round {number}/3 ===", flush=True)
    subprocess.run(
        [sys.executable, "-B", str(script)],
        check=True, stdin=subprocess.DEVNULL,
    )
CHECK
```

## 4. Inspect evidence

Each run prints its evidence directory under ~/Work/oai-test-evidence.

Set the path printed by the validator:

```bash
EVIDENCE="$HOME/Work/oai-test-evidence/ocudu-kpm-rejection-REPLACE_WITH_RUN_ID"
cat "$EVIDENCE/summary.json"
```

Inspect protocol and failure logs:

```bash
cat "$EVIDENCE/probe.json"
cat "$EVIDENCE/probe.stdout"
cat "$EVIDENCE/probe.stderr"
cat "$EVIDENCE/ric.log"
cat "$EVIDENCE/gnb-e2.log"
```

Check that:

- summary.json reports passed=true with no cleanup errors.
- The unsupported metric returns handle -1.
- The same xApp receives at least three subsequent normal reports.
- Logs contain the rejection and normal delete-response markers.
- The temporary RIC and RAN processes remain alive during the probe.
- The baseline RIC identity remains unchanged.
- The original RAN configuration is restored with gNB and UE stopped.

A timeout, assertion or container exit is a failed run. Preserve the evidence
before changing code or retrying. Do not treat a missing response as rejection.

## 5. Build the test images locally

Stop the experimental gNB and UE before compiling on the Raspberry Pi.

```bash
sudo docker build \
  -f docker/ocudu/Dockerfile.flexric-subscription-failures \
  --target xapp --build-arg BUILD_JOBS=2 \
  -t limx59/oai-pi-ocudu-flexric-xapp:arm64-subscription-failures-test .
```

```bash
sudo docker build \
  -f docker/ocudu/Dockerfile.flexric-subscription-failures \
  --target ric --build-arg BUILD_JOBS=2 \
  -t limx59/oai-pi-ocudu-flexric-ric:arm64-subscription-failures-test .
```

The Dockerfile applies the source-copy patches before compilation.
The repository flexric source directory is not modified.

Patch scripts are in test/ocudu/patches. Review snapshots are in:

- patches/flexric-subscription-failures/original/
- patches/flexric-subscription-failures/patched/
- patches/flexric-subscription-failures/changes.patch
- patches/flexric-subscription-failures/manifest.json
- patches/flexric-v3-failure-encoding/original/
- patches/flexric-v3-failure-encoding/patched/
- patches/flexric-v3-failure-encoding/changes.patch
- patches/flexric-v3-failure-encoding/manifest.json

Apply the six patches in the first manifest's order, followed by
patch-flexric-v3-subscription-failure-encoding.py.
Docker builds use the patch scripts; snapshots are review material.

## 6. Test boundary

This procedure validates unsupported-metric rejection, subsequent normal
subscription recovery in the same xApp, and a normal delete response.

It does not validate deletion rejection, timeout recovery, duplicate failure
messages, optional diagnostic decoding, all report styles, or complete E2AP
conformance. It does not check post-delete silence in this probe.
