# Experimental OAI UE handover and closed-loop feedback

Validated on ARM64 Raspberry Pi on 2026-10-12, Pacific time.
This completes the bounded RFsim UE handover and closed-loop feedback
subcase of the original Traffic steering control test case.
Dedicated test images are not replacements for regular images.

## Topology and validated behavior

One UE is the RFsim server at 172.29.0.32. Both gNBs are clients.
Node A is 3584, NR cell 12345678, PCI 0; node B is 2816,
NR cell 720898, PCI 1. PLMN is 00101, with 24 PRB and numerology 1.
Container CPU sets are A=1, B=2, UE=3.

The controller reads actual OAI MAC cumulative UL byte counters.
It requires three consecutive one-second windows at or above
100000 MAC bytes/s, fresh reports, stable RNTI and increasing counters.
This is an experimental traffic-rate trigger, not a cell-capacity,
normalized-utilization or overload model.

An empty cell emits no MAC report in this OAI implementation.
Missing MAC reports are never interpreted as zero load.
A fresh RC Style 5 inventory must explicitly identify the target cell
and report zero UEs before a request is eligible.

The controller queries the source UE context and neighbour before
sending an E2 RC Style 3 handover request. The validator independently
checks target RRC completion and NGAP Handover Notify, target PDU session,
source UE removal, unchanged UE IPv4 address, 5/5 post-control pings,
target MAC counter growth and unchanged RIC/gNB/UE process identities.
MAC and RC subscriptions must be deleted normally.

Two real 25-second, 1 Mbps UDP uplink bursts trigger A -> B -> A.
A 30-second cooldown and three low-rate windows at or below 25000 MAC
bytes/s rearm the policy. Each controller invocation permits at most
two actions. Control remains blocked while feedback is pending.
The validator waits for a fresh measured low-rate baseline before traffic.

Three local-image and three published-image regression rounds passed.
Each three-round sequence preserves the same four processes and session,
and explicitly verifies NCC 7 -> 0 rollover without integrity failures.
Published evidence is regression-mai1codl.
Archive: oai-n2-closed-loop-regression-20261012-114919-regression-mai1codl.tar.gz
under ~/Work/oai-test-evidence/.

## NCC failure and isolated correction

Repeated handovers with the original UE reached NCC 7 -> 0.
The UE skipped NH synchronization and key derivation; target PDCP
reported integrity failures, and RRC completion was not confirmed.
The failed run remains archived as
oai-n2-closed-loop-ncc-failure-20261012-012804.tar.gz.

[apply-oai-ue-ncc-wrap.py](patches/apply-oai-ue-ncc-wrap.py) changes only
the Docker copy /src/oai/openair2/RRC/NR_UE/rrc_UE.c.
It retains a cumulative local NH derivation count and compares its
low three bits with received NCC. Initial zero is distinct from rollover.
Integrity checks remain enabled. The existing initial NAS COUNT convention
is retained; general security-context changes and reestablishment are
not validated by these handover tests.

C checks using stub derivation functions covered three counter cycles,
horizontal derivation and skipped-count synchronization. Runtime
regressions separately verified successful handovers across rollover.
Repository OAI and FlexRIC source trees remain unchanged.

A published-image validation also exposed a fixed-delay readiness race.
That failed run remains failed. The validator now waits for an actual
valid low-rate decision before generating traffic.

## Published images

| Component | Image | Image-index digest |
| --- | --- | --- |
| gNB | `limx59/oai-pi-oai-gnb:arm64-rc-handover-test` | `sha256:64bca8439d993adf483528ece58c95b29b8096a4dec422fc5631a896e169243b` |
| RIC | `limx59/oai-pi-flexric-ric:arm64-oai-rc-test` | `sha256:b5503f6a97ecd486cfe145a31f0ce1880bd46a8e44478fe902a07f335c36f839` |
| UE | `limx59/oai-pi-oai-nr-ue:arm64-ncc-wrap-test` | `sha256:6baeb7cc96a1cfeec8e0372327593e7b8fbf301fb572f467f1b5520a133d7c7a` |
| Bidirectional control xApp | `limx59/oai-pi-flexric-xapp:arm64-oai-n2-bidirectional-test` | `sha256:dd15cfe9875ea8df3040001eaa098747c157f43594c543d2abe1b07ed5dbf1d3` |
| Cell inventory and MAC collector | `limx59/oai-pi-flexric-xapp:arm64-oai-cell-inventory-test` | `sha256:21b208b26160e2c230f807aaa45b981ebaec33acaa3b7eab23258c2e5ffd80cb` |

Tags are mutable; index digests differ from runtime image IDs.
The temporary traffic server uses the existing limx59/oai-nr-ue:arm64
image and adds its route only inside that temporary container.

## Reproduction

Use the matched OAI SDK RIC, INI configuration and existing Open5GS core.
See [the original N2 guide](README.oai-n2-handover.md) for prerequisites.
Keep UE credentials local. Required external networks and addresses
must be available. Run from the repository root.

```bash
sudo docker pull limx59/oai-pi-oai-nr-ue:arm64-ncc-wrap-test
sudo docker pull limx59/oai-pi-flexric-xapp:arm64-oai-n2-bidirectional-test
sudo docker pull limx59/oai-pi-flexric-xapp:arm64-oai-cell-inventory-test
compose=(sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  -f deploy/oai-flexric/compose.oai-n2-handover.yaml \
  -f deploy/oai-flexric/compose.oai-rc-sdk.yaml \
  -f deploy/oai-flexric/compose.oai-n2-cpu-isolated.yaml \
  -f deploy/oai-flexric/compose.oai-n2-ncc-wrap.yaml)
"${compose[@]}" --profile ue --profile tools config --quiet
```

Reset only when this experiment project has no other active work:

```bash
"${compose[@]}" --profile ue stop --timeout 15 nrue gnb gnb-2
"${compose[@]}" up -d --no-build --pull never --no-deps --force-recreate ric
"${compose[@]}" up -d --no-build --pull never --no-deps --force-recreate gnb
```

Confirm source NG/F1/E2 setup before starting the UE:

```bash
"${compose[@]}" --profile ue up -d --no-build --pull never \
  --no-deps --force-recreate nrue
```

Confirm PCI 0 synchronization, PDU session and TUN address before B:

```bash
"${compose[@]}" up -d --no-build --pull never \
  --no-deps --force-recreate gnb-2
"${compose[@]}" --profile ue exec -T nrue \
  ping -I oaitun_ue1 -c 5 -W 3 192.168.100.1
```

Confirm target NG/F1/E2 setup. The controller requires one UE on A,
zero UEs on B and unchanged healthy processes. It does not reset RAN.
Run an initial round, then three rounds in the same session to include
NCC rollover. Do not restart containers between these commands:

```bash
python3 test/flexric/validate-oai-n2-closed-loop.py \
  --output-dir /tmp/oai-n2-closed-loop-initial </dev/null
python3 test/flexric/validate-oai-n2-closed-loop-regression.py \
  --output-dir /tmp/oai-n2-closed-loop-regression </dev/null
```

The wrapper stops on failure and archives evidence even on failure.
A valid initial round is required before the three-round sequence when
starting a fresh session: six handovers alone may not cross NCC rollover.
The traffic server address 172.22.0.151 must be free.
The validator owns and removes its temporary server; RAN remains running
for further inspection. Inspect state after a failure before retrying.

## ICMP observation and boundaries

```bash
python3 test/flexric/measure-oai-n2-roundtrip.py \
  --output-dir /tmp/oai-n2-roundtrip </dev/null
```

This sends explicit bidirectional requests in the existing healthy topology.
It requires UE initially on A and leaves UE back on A.
It is separate from the actual-load-driven controller run.

| Measurement | Sent / received | Maximum observed ICMP reply gap |
| --- | --- | --- |
| Patched local UE, run-mr_04mes | 1184 / 1181 | 0.316799 s |
| Published images, run-wfl7jbcx | 1185 / 1182 | 0.300538 s |

Probe spacing is 0.1 seconds. Each run lost three replies.
The gaps include probe spacing, RTT and scheduling; they are not exact
radio interruption times. No zero-loss or interruption SLA is claimed.

This validates one UE transferring to an explicitly empty cell.
It does not establish simultaneous two-UE traffic, normalized multi-cell
load balancing, throughput improvement, physical RF performance,
cross-RIC policy aggregation or production availability.
The separate dual-UE RFsim steering-policy case remains deferred.

## Cleanup

Save evidence, then remove only this experiment project:

```bash
"${compose[@]}" --profile ue stop --timeout 15 nrue gnb gnb-2
"${compose[@]}" --profile ue --profile tools down --remove-orphans
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-oai-e2-lab \
  --format 'table {{.Names}}\t{{.Status}}'
```

Open5GS, UERANSIM, redroid, external networks, images, subscribers and
local credentials are retained.
