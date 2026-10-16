# KPM monitoring: abrupt xApp disconnection scenario

## Purpose and scope

This scenario belongs to the existing KPM monitoring test case.
It is not an additional top-level TODO item.

The environment combines OCUDU gNB, OAI NR UE over ZeroMQ, existing
Open5GS, FlexRIC RIC and the KPM CSV recorder.

After at least two KPM receive timestamps, the test forcibly kills the
subscribed xApp container. It checks automatic subscription deletion,
RIC survival and the absence of continued indications after deletion.
A new xApp then performs the existing bounded UL/DL UDP and CSV tests.

## Images

| Role | Image |
| --- | --- |
| RIC | limx59/oai-pi-ocudu-flexric-ric:arm64-e2ap3-kpm3-disconnect-fix |
| xApp | limx59/oai-pi-ocudu-flexric-xapp:arm64-e2ap3-kpm3-node-id-fix |
| gNB | limx59/oai-pi-ocudu-gnb:arm64-zmq-worker-test |
| UE / traffic server | limx59/oai-pi-oai-nr-ue:arm64-zmq-test |

Published RIC digest:

`sha256:ab7371fa9a1deac31b393823000ca8247a8bf4db19527e744287c2a35b15d8c5`

The RIC candidate passed a local single round and three-round regression
before publication. Its Docker Hub push/pull digests matched, and the
published reference subsequently passed three rounds.

## Fix

test/ocudu/patches/patch-flexric-ric-disconnect.py is applied to the
Docker source copy by docker/ocudu/Dockerfile.flexric.

It adds an optional connection lookup under the existing read lock.
Forwarding paths tolerate a missing xApp connection. Delete responses
and control acknowledgements still remove their request mappings.

The original interrupted run exposed an assertion while looking up a
disconnected xApp. Historical crash evidence is retained. The new tests
cover the explicit container-kill scenario described here.

## Prerequisites

Use the prerequisites in README.zmq-kpm.md. Stop the experiment's gNB
and UE first; the validator starts them itself. Keep the existing core
available and avoid concurrent subscriptions to the same DU.

The selected RIC must already be running, with its configured image
reference matching --ric-image.

The script reuses validate-zmq-kpm.py and validate-zmq-connectivity.py.
The original normal-flow validator remains available separately.

## Execution

Run from ~/Work/oai-5gc-pi-review.

Pull the published RIC:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-ric:arm64-e2ap3-kpm3-disconnect-fix
```

Recreate RIC with the selected reference:

```bash
sudo env OCUDU_RIC_IMAGE=limx59/oai-pi-ocudu-flexric-ric:arm64-e2ap3-kpm3-disconnect-fix \
  docker compose \
  -f deploy/ocudu/compose.zmq.yaml \
  -f deploy/ocudu/compose.zmq-worker-test.yaml \
  -f deploy/ocudu/compose.e2.yaml \
  up -d --no-deps --force-recreate --no-build --pull never ric
```

Run three rounds:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 test/ocudu/validate-zmq-kpm-disconnect.py \
  --ric-image limx59/oai-pi-ocudu-flexric-ric:arm64-e2ap3-kpm3-disconnect-fix \
  --rounds 3 \
  --output-dir /tmp/ocudu-zmq-kpm-disconnect-dockerhub-regression \
  </dev/null
```

The required --ric-image argument also supplies OCUDU_RIC_IMAGE to
the validator's Docker/Compose commands. Local candidate testing can
use an explicit local reference before publication.

## Acceptance

Before fault injection, at least two distinct KPM receive timestamps
and the expected node subscription must be observed.

The injected container kill must result in exit code 137.
For a 20-second polling interval after the kill, RIC and RAN process
identities must remain unchanged. UE address must also remain unchanged.

The gNB must emit exactly one automatic subscription delete response.
No E2 indication may be observed beyond one second after that response,
with at least five seconds of post-response observation.

RIC logs must show disconnection and automatic pending-subscription
cleanup without an observed assertion, abort or segmentation fault.

A new xApp must then pass the normal UL/DL CSV and deletion checks.
Each direction offers 1 Mbps UDP for 10 seconds. Receiver throughput
must be at least 800,000 bit/s and packet loss no greater than 5%.

## Results

Local single round and local three-round regression passed.

Published-reference regression on 2026-10-16, Pacific time:

| Round | UL received bit/s | DL received bit/s | UL / DL loss | UL / DL CSV rows |
| --- | ---: | ---: | --- | --- |
| 1 | 993226 | 1001197 | 0% / 0% | 20 / 20 |
| 2 | 993666 | 999345 | 0% / 0% | 20 / 18 |
| 3 | 993491 | 1001219 | 0% / 0% | 18 / 18 |

All three fault-injection phases passed. New subscriptions and normal
cleanup passed, with 114 post-fault UL/DL CSV rows and zero measured
packet loss across all six traffic directions.

## Evidence

| Run | Directory |
| --- | --- |
| Local single | /tmp/ocudu-zmq-kpm-disconnect-local/run-5ac90lbu |
| Local three | /tmp/ocudu-zmq-kpm-disconnect-local-regression/run-1nk17huy |
| Docker Hub three | /tmp/ocudu-zmq-kpm-disconnect-dockerhub-regression/run-2ygdbv4_ |

Verified archive under ~/Work/oai-test-evidence/:

`ocudu-kpm-disconnect-20261016-114442.tar.gz`

Archive sections: local-single, local-three and dockerhub-three.
Each round includes disconnect/summary.json and related fault evidence.
The round summary also includes the subsequent normal UDP/KPM results.

## Cleanup and limitations

The validator removes its xApp and traffic containers and stops gNB/UE.
RIC and the shared core remain. Follow README.zmq-kpm.md for complete
experiment cleanup.

This validates the observed container-kill scenario. It does not establish
recovery from network blackholes, host failure, all SCTP association-loss
events, or RIC/Agent restarts. Process checks are sampled.

KPM monitoring remains in progress: exact one-second wall-clock cadence,
other report styles and unsupported subscriptions still require work.
Actual UE identifiers, units and measurement accuracy remain unvalidated.
Physical RF is outside this software-radio test.
