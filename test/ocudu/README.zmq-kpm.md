# OCUDU DU KPM and CSV validation

## Scope

This test combines the OCUDU DU, OAI NR UE over ZeroMQ, existing Open5GS,
FlexRIC nearRT-RIC and a Python CSV recorder.

The validated subset is a DU KPM subscription using action Format 4 and
indication Format 3, with DRB.UEThpDl and DRB.UEThpUl measurements during
bounded directional UDP traffic. It does not establish complete protocol
conformance, control support or physical RF operation.

## Environment

| Component | Address / setting |
| --- | --- |
| Docker network | docker_open5gs_default |
| OCUDU gNB | 172.22.0.160; CPU set 1-2 |
| OAI NR UE | 172.22.0.161; CPU set 3 |
| FlexRIC RIC | 172.22.0.162 |
| Temporary traffic server | 172.22.0.151 |
| UPF | 172.22.0.8 |
| UPF tunnel endpoint | 192.168.100.1 |
| Observed DU identity | Node 420; DU ID 0; PLMN 001/01 |
| Offered UDP load | 1 Mbps; 10 seconds per direction |
| Round lifecycle | Fresh gNB/UE containers; retained RIC and core |

CPU sets do not reserve exclusive CPU capacity.

## Prerequisites

Run from ~/Work/oai-5gc-pi-review. The existing Open5GS environment and
external Docker network must be healthy. Running container state alone
does not prove successful SBI communication.

The validator requires:

- sudo access to Docker.
- The existing private UE configuration.
- No running OCUDU gNB/UE experiment.
- No existing oai-pi-ocudu-traffic container or occupied 172.22.0.151 address.
- A running RIC.
- The local helper validate-zmq-connectivity.py and existing xApp scripts.
- No concurrent xApp subscriptions to the same DU during deletion checks.

Do not include private UE credentials in documentation or shared logs.

### Core SBI recovery observation

Core SBI listener and configured NRF/SCP URIs were checked at port 7777.
During earlier failures, SCP nevertheless attempted downstream HTTP
connections on port 80, followed by authentication-chain HTTP 500 errors.

Restarting AUSF restored registration, PDU session establishment and
TUN-bound connectivity in the observed environment. This was operational
recovery; the underlying port-selection failure remains unresolved.

The validator does not restart core services automatically. There is no
evidence that a UE or OCUDU SBI port setting is required to correct this
core-internal failure.

## Images and patch

| Role | Image |
| --- | --- |
| gNB | limx59/oai-pi-ocudu-gnb:arm64-zmq-worker-test |
| UE / traffic server | limx59/oai-pi-oai-nr-ue:arm64-zmq-test |
| RIC | limx59/oai-pi-ocudu-flexric-ric:arm64-e2ap3-kpm3-test |
| xApp | limx59/oai-pi-ocudu-flexric-xapp:arm64-e2ap3-kpm3-node-id-fix |

All listed images are published on Docker Hub. The RIC and xApp were
pushed and pulled successfully on 2026-10-16, Pacific time. Their registry
digests matched the push results:

| Image | Registry digest |
| --- | --- |
| RIC | sha256:6d4071b6ed77137a9169663b563a04236734fe439fc945625c201d2149920986 |
| xApp | sha256:e89667f1d8acc348126b3b8651fd41182919408dd58131d41d89afcc94624a21 |

compose.e2.yaml and the validator default use these published references.
Pull both images before running with the configured never-pull policy:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-ric:arm64-e2ap3-kpm3-test
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-e2ap3-kpm3-node-id-fix
```

docker/ocudu/Dockerfile.flexric selects E2AP V3 and KPM V3.00.
Its xApp source-copy patch is:

test/ocudu/patches/patch-flexric-swig-node-id.py

The patch preserves optional scalar CU/DU IDs across the SWIG boundary
and performs explicit conversion when submitting KPM subscriptions.
It runs against the Docker source copy before compilation.

This patch does not fix the RIC abnormal-disconnection crash.

OCUDU and FlexRIC service-model metadata differ. Successful operation
of this tested subset must not be described as full version compatibility.

## Configuration

The experiment uses these Compose files in order:

1. deploy/ocudu/compose.zmq.yaml
2. deploy/ocudu/compose.zmq-worker-test.yaml
3. deploy/ocudu/compose.e2.yaml

E2 configurations are under deploy/ocudu/config:

- gnb-zmq-e2.yml
- ric.conf
- xapp.conf

DU E2 and KPM are enabled; CU-CP E2, CU-UP E2 and RC are disabled.
RIC ports are 36421 for E2 and 36422 for E42.

The gNB needs RLC metric production:

```yaml
metrics:
  layers:
    enable_rlc: true
  periodicity:
    du_report_period: 1000
```

Without enable_rlc, subscriptions were accepted but no KPM reports were
observed. Enabling it connected the RLC metric producer to the DU E2
consumer.

cu_cp.request_pdu_session_timeout is set to 30 seconds as a diagnostic
allowance. It does not correct SBI connection failures.

The reused Python SDK constructs action Format 4. The tested DU returns
indication Format 3. S-NSSAI filtering behavior has not been validated.

## Execution

Start the RIC if it is stopped:

```bash
cd ~/Work/oai-5gc-pi-review

sudo docker compose \
  -f deploy/ocudu/compose.zmq.yaml \
  -f deploy/ocudu/compose.zmq-worker-test.yaml \
  -f deploy/ocudu/compose.e2.yaml \
  up -d --no-deps --no-build --pull never ric
```

The validator starts gNB and UE itself. Do not start them separately.

Single round:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 test/ocudu/validate-zmq-kpm.py \
  --rounds 1 --output-dir /tmp/ocudu-zmq-kpm \
  </dev/null
```

Three fresh-container rounds:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 test/ocudu/validate-zmq-kpm.py \
  --rounds 3 --output-dir /tmp/ocudu-zmq-kpm-regression \
  </dev/null
```

Each direction uses an evidence-directory copy of xapp_kpm.py with a
20-second subscription interval and a six-second deletion observation
delay. Repository xApp scripts are not modified by this mechanism.

If the terminal connection may close, use a persistent execution session.
An interrupted run without a completed summary is not a passed result.

## Acceptance checks

The validator checks:

- TUN address establishment and five successful traffic-endpoint pings
  before and after the directional tests.
- Receiver throughput of at least 800,000 bit/s for a 1 Mbps offered load,
  packet loss no greater than 5%, and positive received bytes.
- Expected node, PLMN, RAN type, indication format and metric names.
- Complete finite numeric CSV values with UTC receive timestamps.
- At least two later positive reports for the loaded direction.
- Successful normal subscription deletion.
- No indication sends or CSV callbacks beyond a one-second deletion grace
  period, with at least five seconds of observation.
- Stable sampled gNB, UE and RIC process identities and UE address.
- Successful cleanup of owned temporary containers and stopping of RAN.

The positive-report check uses receive timestamps around the traffic
interval. These are not verified measurement collection windows.
Sampled process checks are not continuous UE-context monitoring.

A final in-flight report can arrive around the deletion response.
Continued local RLC metric generation is not evidence of a remaining
E2 subscription.

## Results

The successful single-round run recorded 18 CSV rows per direction.
UL receiver throughput was 993,922 bit/s and DL was 1,001,223 bit/s,
both with zero packet loss.

Three fresh-container rounds passed:

| Round | UL received bit/s | DL received bit/s | UL / DL loss | UL / DL CSV rows |
| --- | ---: | ---: | --- | --- |
| 1 | 995080 | 1000226 | 0% / 0% | 20 / 20 |
| 2 | 994802 | 1000287 | 0% / 0% | 18 / 18 |
| 3 | 993754 | 1000224 | 0% / 0% | 20 / 18 |

All six directional phases passed positive-value and normal deletion
checks. The regression produced 114 CSV rows and completed cleanup.

Idle subscriptions previously produced zero throughput values. Concurrent
ping traffic produced positive UL and DL values with 150/150 replies.

Despite a configured 1000 ms period, observed wall-clock receive gaps
varied; the single-round UDP test included gaps of roughly 1.2 to
4.6 seconds. Precise one-second wall-clock reporting has not passed.

## Docker Hub reference regression

On 2026-10-16, Pacific time, RIC was recreated using the published reference.
The validator then passed three fresh-RAN rounds using the published xApp,
gNB and UE references, without rebuilding images.

| Round | UL received bit/s | DL received bit/s | UL / DL loss | UL / DL CSV rows |
| --- | ---: | ---: | --- | --- |
| 1 | 994441 | 1001189 | 0% / 0% | 20 / 20 |
| 2 | 994850 | 1001252 | 0% / 0% | 20 / 20 |
| 3 | 993183 | 1000225 | 0% / 0% | 18 / 18 |

All six directional phases passed positive-value, normal deletion and
cleanup checks, with 116 CSV rows in total. Existing limitations still apply,
including the unresolved abrupt-disconnection crash.

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 test/ocudu/validate-zmq-kpm.py \
  --rounds 3 \
  --xapp-image limx59/oai-pi-ocudu-flexric-xapp:arm64-e2ap3-kpm3-node-id-fix \
  --output-dir /tmp/ocudu-zmq-dockerhub-kpm-regression \
  </dev/null
```

Evidence directory:

`/tmp/ocudu-zmq-dockerhub-kpm-regression/run-jrzfzyab`

Verified archive under `~/Work/oai-test-evidence/`:

`ocudu-dockerhub-kpm-regression-20261016-104059.tar.gz`

## Evidence

Successful single-round directory:

~/Work/oai-test-evidence/ocudu-kpm-background-20261015-211428/evidence/run-gvekz3nd

Successful three-round directory:

/tmp/ocudu-zmq-kpm-regression/run-b63dorm3

Interrupted-run directory:

/tmp/ocudu-zmq-kpm/run-x74j4m14

Verified archive:

~/Work/oai-test-evidence/ocudu-kpm-csv-20261015-214428.tar.gz

Archive sections are single-round, three-round and interrupted-run.
Evidence includes summaries, CSV files, iperf results and relevant logs.
Keep failed-run evidence as well as successful results.

## Known abnormal-disconnection failure

During the interrupted run, the xApp exited with code 129. RIC logs showed
xApp disconnection, automatic pending-subscription removal and then:

```text
map_xapps_sockaddr.c:194: find_map_xapps_sad:
Assertion `it != end && "xApp ID not found in the tree"' failed.
```

The RIC container exited with code 133. Terminal disconnection is a
plausible trigger for the xApp interruption, but the available evidence
does not prove the entire causal chain.

The normal-operation regressions passed after restarting RIC. They do
not demonstrate that this abnormal-disconnection defect is fixed.

Next work is to fix pending-subscription cleanup and separately validate
RIC survival, Agent cleanup and xApp reconnection.

## Cleanup

The validator stops gNB/UE and removes its temporary xApp and traffic
containers. RIC and the shared core remain available.

Inspect leftovers:

```bash
sudo docker ps -a --filter name=ocudu \
  --format 'table {{.Names}}\t{{.Status}}'
```

After evidence collection, remove the experiment's Compose containers:

```bash
sudo docker compose \
  -f deploy/ocudu/compose.zmq.yaml \
  -f deploy/ocudu/compose.zmq-worker-test.yaml \
  -f deploy/ocudu/compose.e2.yaml \
  --profile ue down
```

Review any additional temporary container by exact name before removing
it. Retain the external core network and unrelated services.

## Remaining limitations

- Actual UE identifiers and CSV CU/DU identity fields are not validated;
  ue_report_index is only a position within a report.
- Units, measurement accuracy and collection windows are not validated.
- One-second wall-clock cadence is not established.
- RIC abrupt-disconnection recovery remains defective.
- The earlier core SBI port-selection failure has no confirmed root cause.
- Long-duration stability, capacity, RC, slicing and physical RF are outside
  this bounded result.
