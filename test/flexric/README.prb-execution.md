# Experimental multi-Agent PRB allocation execution

Validated on ARM64 Raspberry Pi on 2026-10-12, Pacific time.
This extends the original Multi-Agent slicing control test case with
E2-triggered independent real NR downlink scheduler simulations.

## Execution scope

The xApp sends custom SLICE ADD/MOD control through a RIC to one selected
Emulator Agent. The Agent validates three slice IDs (0, 1, 2), NVS capacity
fields, integer percentages and a total of 100 percent.

For this dedicated experiment, capacity fractions are interpreted as hard
per-slot PRB caps. This is not a validation of the native NVS algorithm or
O-RAN E2SM-RC slicing semantics.

Each valid command starts a new standalone nr_dlbench process: three
synthetic UEs, 106 PRBs, numerology 1 and 200 downlink slots.
The benchmark injects data into real RLC entities and runs the actual
NR MAC scheduler, PDSCH generation and PHY TX chain.
HARQ feedback and UE state are simulated; there is no RFsim UE receiver.

UE RNTIs 0x1234, 0x1235 and 0x1236 are assigned laboratory S-NSSAIs
SST=1, SD=1,2,3 respectively through scheduler logical-channel metadata.
The allocation policy groups candidates by S-NSSAI and uses the existing
CCE/PUCCH validation and VRB commit functions.

Each cap is floor(available PRBs * percentage / 100).
Available PRBs are the scheduler's current budget, not always the configured
106-PRB bandwidth. Integer rounding, common-channel reservations,
fragmentation and control-channel limits can leave resources unused.
Slices cannot borrow unused caps. Caps are upper bounds, not guaranteed shares.
The policy includes a retransmission cap path; nonzero-BLER regression
and multiple UEs per slice have not been validated.

The executor compares actual scheduler-generated PDSCH grants against
per-slot policy records, checks bounds, non-overlap, positive transport
blocks and zero-quota suppression. It returns success only after verification.
The Agent then returns SLICE_CTRL_OUT_OK; other paths return ERROR.
Live tests cover successful execution and client-side rejection.
Agent-side invalid payloads and execution-failure responses remain untested.

No scheduler state survives between benchmark invocations.
RIC and Agent processes remain running, but each command creates a fresh
scheduler simulation. Other Emulator service-model reports remain synthetic;
the slice indication callback is suppressed to avoid random slice reports.

## Published images

| Component | Image |
| --- | --- |
| RIC | limx59/flexric-ric:arm64-multi-agent |
| Execution Agent | limx59/oai-pi-flexric-emulator:arm64-prb-execution-test |
| Control xApp | limx59/oai-pi-flexric-xapp:arm64-prb-execution-test |

Agent image-index digest:
sha256:05d560f12adff77bf10a89b42f96a70f44a43e387b11368b31ce0ccc5bfa5d87

xApp image-index digest:
sha256:96addca036ad5c1228f7a871228b5c92d3a8c1791b63aec10a58e7d5057e051a

Both published images were pulled and their ARM64 architecture and digests
verified. The xApp runs its packaged script without a local source mount.
The Agent image contains the executor, benchmark binary and LDPC modules.

## Deployment

Run from the repository root. The existing external network
oai-pi-flexric-lab must be present. Confirm addresses 172.29.0.10,
172.29.0.20, 172.29.0.21 and 172.29.0.22 are free.

```bash
sudo docker pull limx59/oai-pi-flexric-emulator:arm64-prb-execution-test
sudo docker pull limx59/oai-pi-flexric-xapp:arm64-prb-execution-test
sudo docker pull limx59/flexric-ric:arm64-multi-agent
```

```bash
sudo docker compose -p oai-pi-prb-execution-lab \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.prb-execution.yaml \
  up -d --no-build --pull never ric emulator emulator-2 emulator-3
```

Wait for all three Agents' E2 SETUP RESPONSE before validation.
Nodes 1, 2 and 3 use the three Agent addresses respectively.

## Automated validation and regression

```bash
python3 test/flexric/validate-prb-execution.py \
  --output-dir /tmp/oai-e2-prb-validation </dev/null
```

Each round checks 11 cases:

- Empty, incorrect-sum, negative and overflowing quota inputs reject
  before xApp initialization.
- Missing node 99 rejects without control transmission.
- Nodes 1, 2 and 3 each execute 45/40/15 at the selected Agent only.
- Node 2 executes swapped 15/40/45, zero 0/50/50 and restored 45/40/15.

Each successful case copies raw scheduler evidence out of the target
container, corrects ownership and independently audits the PDSCH grants
on the host. RIC and all three Agent identities remain unchanged.

```bash
python3 test/flexric/validate-prb-execution-regression.py \
  --output-dir /tmp/oai-e2-prb-regression </dev/null
```

The reusable regression runs three rounds, stops on failure, verifies
cross-round process identities and archives success or failure evidence.
It supports --project, --xapp-image, --output-dir and --archive-dir.
It requires an existing healthy topology and leaves it running.

Three local-image rounds and three published-image rounds passed:
33 checks and 18 independently audited scheduler executions per sequence.

Published regression: regression-u009ptqp.
Archive: oai-e2-prb-regression-20261012-201909-regression-u009ptqp.tar.gz
under ~/Work/oai-test-evidence/.

## Isolated builds

Repository OAI and FlexRIC sources remain unchanged.
New patches are maintained under test/flexric/patches and applied only to
Docker's copied source trees.

Build the local benchmark dependency first:

```bash
sudo docker build -f docker/oai/Dockerfile.nr-prb-quota \
  --target bench --build-arg BUILD_JOBS=2 \
  -t oai-pi-oai-prb-bench:nr-prb-quota-test .
```

Then build the Agent and xApp:

```bash
sudo docker build -f docker/flexric/Dockerfile.prb-execution \
  --target emulator --build-arg BUILD_JOBS=2 \
  -t oai-pi-flexric-emulator:prb-execution-test .
sudo docker build -f docker/flexric/Dockerfile.prb-control \
  --target xapp -t oai-pi-flexric-xapp:prb-execution-test .
```

Dockerfile.nr-prb-bench provides the unmodified scheduler baseline.
Dockerfile.nr-prb-trace adds actual grant records.
Dockerfile.nr-prb-quota adds the benchmark-only cap policy.
Standalone benchmark builds disable E2_AGENT and explicitly build the
runtime-loaded ldpc and ldpc_orig modules.
The dedicated Emulator provides the E2 control connection separately.

## Cleanup

```bash
sudo docker compose -p oai-pi-prb-execution-lab \
  -f deploy/oai-flexric/compose.emulator.yaml \
  -f deploy/oai-flexric/compose.multi-agent.yaml \
  -f deploy/oai-flexric/compose.prb-execution.yaml \
  down --remove-orphans
```

Preserve images, external networks and archived evidence.
Open5GS, UERANSIM, ReDroid and host networking are outside this experiment.

## Remaining boundaries

Continuous live-gNB scheduler control, real UE reception/performance,
uplink slicing, multi-RIC execution, multiple UEs per slice, fairness,
nonzero-BLER behavior, Agent execution-failure recovery and production
workload isolation remain unvalidated.
