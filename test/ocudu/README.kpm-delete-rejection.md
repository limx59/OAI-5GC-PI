# KPM subscription delete rejection test

## Prerequisites

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

This test requires the existing Open5GS deployment, private UE configuration,
docker_open5gs_default network, and baseline RIC running at 172.22.0.162.
Address 172.22.0.163 must be available for the temporary test RIC.
The experimental gNB and UE must be stopped. Do not run concurrent xApps.

Follow README.kpm-subscription-rejection.md for the baseline prerequisites
and RAN stop command. Keep the baseline RIC and shared core running.

## Pull published images

The following ARM64 tags were pushed and pulled successfully on 2026-10-19.
Use these images to skip local compilation.

```bash
sudo docker pull limx59/oai-pi-ocudu-gnb:arm64-kpm-delete-rejection-test
sudo docker pull limx59/oai-pi-ocudu-flexric-ric:arm64-delete-rejection-test
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-delete-rejection-test
```

## Build images

Build on ARM64 with the experimental RAN stopped:

```bash
sudo docker build \
  -f docker/ocudu/Dockerfile.kpm-delete-rejection-test \
  --target gnb --build-arg BUILD_JOBS=2 \
  -t limx59/oai-pi-ocudu-gnb:arm64-kpm-delete-rejection-test .
```

```bash
sudo docker build \
  -f docker/ocudu/Dockerfile.flexric-delete-rejection \
  --target xapp --build-arg BUILD_JOBS=2 \
  -t limx59/oai-pi-ocudu-flexric-xapp:arm64-delete-rejection-test .
```

```bash
sudo docker build \
  -f docker/ocudu/Dockerfile.flexric-delete-rejection \
  --target ric --build-arg BUILD_JOBS=2 \
  -t limx59/oai-pi-ocudu-flexric-ric:arm64-delete-rejection-test .
```

The Dockerfiles apply patches to build-stage source copies.
Repository upstream source directories remain unchanged.
Runtime images do not contain the source tree or compiler.

## Run one round

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  test/ocudu/validate-kpm-delete-rejection.py </dev/null
```

The validator creates a temporary RIC and uses a temporary Compose override
to select the test gNB image and enable OAI_PI_TEST_REJECT_FIRST_DELETE=1.
This explicitly rejects the first existing-subscription deletion per
subscription manager. The subscription remains active.
A second deletion follows the normal path.

The probe uses Style 4 and checks Format 3 indications.
The validator verifies correlated rejection forwarding and event order,
continued reporting, successful retry, stable process identities, and
post-delete silence at both gNB sender and xApp callback.

At completion, temporary containers are removed and the original RAN
configuration is restored with gNB and UE stopped.
The baseline RIC remains running.

## Repeat three rounds

```bash
python3 - <<'CHECK'
from pathlib import Path
import subprocess
import sys

script = Path("test/ocudu/validate-kpm-delete-rejection.py")
for number in range(1, 4):
    print(f"\n=== Delete rejection round {number}/3 ===", flush=True)
    subprocess.run(
        [sys.executable, "-B", str(script)],
        check=True, stdin=subprocess.DEVNULL,
    )
CHECK
```

## Evidence and acceptance

Each run prints a directory under ~/Work/oai-test-evidence.

Inspect summary.json, probe.json, probe.stdout, probe.stderr, ric.log
and gnb-e2.log. A passing run requires:

- Exactly one injected rejection and one gNB delete-failure message.
- A correlated iApp failure and xApp KPM_DELETE_REJECTED marker.
- At least three reports and gNB sends after the first-delete grace period.
- Successful retry using the same xApp handle.
- Exactly one normal gNB delete response.
- No late sends or callbacks beyond the one-second final-delete grace.
- At least five seconds of observation beyond that grace.
- No process identity changes during the probe or cleanup errors.

A timeout, assertion, missing response or process exit is a failure.
Preserve failed-run evidence before retrying.

Three rounds passed on Raspberry Pi ARM64 on 2026-10-19 PDT:

| Evidence directory suffix | Reports after rejection | Sender guard | Late sends/callbacks |
| --- | ---: | ---: | --- |
| 1oclh7rw | 5 | 6.001018 s | 0 / 0 |
| eqf9574k | 5 | 6.001005 s | 0 / 0 |
| 3smslloz | 5 | 6.000701 s | 0 / 0 |

Each directory has prefix ocudu-kpm-delete-rejection-.
All three probes exited zero, with no cleanup errors.

## Patches and source snapshots

OCUDU additions:

1. patch-ocudu-delete-failure-identity.py copies request correlation fields
   into delete-failure responses.
2. patch-ocudu-test-delete-rejection.py adds explicitly enabled test injection.

FlexRIC additions, after the existing subscription-failure patches:

1. patch-flexric-v3-delete-failure-decoding.py enables mandatory-field
   decoding, validates positional access, and fixes the Cause IE ID.
2. patch-flexric-v3-delete-failure-criticality.py aligns delete-failure
   Cause encoding and decoding with ASN.1 CRITICALITY ignore.

The initial failure was an unconditional Untested code decoder assertion.
The next run exposed an incorrect Cause criticality assertion.
Both failed-run evidence directories were retained:
rhxy1xk4 and bx05pkg0.

Source snapshots, unified diffs, patch order and SHA-256 checksums are in
patches/kpm-delete-rejection/. FlexRIC snapshots there cover codec changes
only; the complete runtime patch sequence is in the Dockerfile.
Existing RIC/iApp/xApp failure-handling snapshots remain in
patches/flexric-subscription-failures/.

## Boundary

This is an injected rejection of a valid subscription, followed by retry.
It does not validate deletion of an absent subscription, timeout recovery,
duplicate failures, optional diagnostics, arbitrary IE ordering,
malformed-message handling, or complete E2AP conformance.

The SDK delete interface is void. Its return alone does not prove a
successful deletion; protocol logs and reporting observations are required.
