# FlexRIC Python xApp Demos

## Demos

| File | Purpose |
| --- | --- |
| xapp_nodes.py | List E2 nodes registered with the RIC |
| xapp_kpm.py | Subscribe to configured KPM metrics |
| xapp_radio_stats.py | Subscribe to MAC, RLC and PDCP reports |
| xapp.conf | Shared local configuration; database writing disabled |

These demos use the standalone FlexRIC Python SDK installed by
scripts/build-flexric.sh. They do not use OAI's embedded FlexRIC checkout.

The default SDK directory is:
 /usr/local/lib/python3/dist-packages/xapp_sdk

Set FLEXRIC_SDK_PATH to override it.

## Validation

Validated on Raspberry Pi 5, ARM64, Debian Bookworm:

- All three demos passed syntax and SDK import checks.
- Node listing connected over E42 and detected one emulated gNB.
- KPM subscription received DRB.UEThpDl and DRB.UEThpUl values.
- MAC, RLC and PDCP callbacks received reports with empty record lists.
- Both monitoring demos cancelled subscriptions and exited.

The emulated gNB uses node ID 1 and PLMN 505/1 in the observed run.
Its metrics are synthetic; they do not measure Open5GS or UERANSIM traffic.
Nonempty MAC/RLC/PDCP records and integration with OAI remain unvalidated.

Monitoring runs for ten seconds after subscription setup.
Callbacks are retained until subscriptions are removed and SDK shutdown ends.

## Run locally

Build and install standalone FlexRIC first; see ../../scripts/README.md.
Run from the project root in Bash. Ensure no other RIC uses these ports.

Start the RIC and emulator, retaining their process IDs in the same shell:

```bash
/usr/local/bin/flexric/ric/nearRT-RIC \
  -c /usr/local/etc/flexric/ric.conf > /tmp/oai-pi-xapp-ric.log 2>&1 &
DEMO_RIC_PID=$!

/usr/local/bin/flexric/e2agent/emu_agent_gnb \
  -c /usr/local/etc/flexric/e2agent.conf > /tmp/oai-pi-xapp-agent.log 2>&1 &
DEMO_AGENT_PID=$!
```

Wait for the emulator to register, then run each demo separately:

```bash
timeout --kill-after=5s 20s python3 test/xapp/xapp_nodes.py \
  -c test/xapp/xapp.conf

timeout --kill-after=5s 30s python3 test/xapp/xapp_kpm.py \
  -c test/xapp/xapp.conf

timeout --kill-after=5s 30s python3 test/xapp/xapp_radio_stats.py \
  -c test/xapp/xapp.conf
```

The timeout is a guard against stalled native SDK initialization or shutdown.
A timeout exit is not a passing test. Normal monitoring completes sooner.

Stop only the emulator and RIC started above, in the same shell:

```bash
kill -INT "$DEMO_AGENT_PID"
wait "$DEMO_AGENT_PID"
kill -INT "$DEMO_RIC_PID"
wait "$DEMO_RIC_PID"
```

Logs are retained under /tmp and must not be committed.

## Configuration and expected output

- RIC address: 127.0.0.1.
- E2 agent port: 36421, configured in e2agent.conf and ric.conf.
- xApp E42 port: 36422, configured in xapp.conf and ric.conf.
- KPM: 1000 ms, gNB, subscription format 4.
- KPM metrics: DRB.UEThpDl and DRB.UEThpUl.
- Custom models: MAC, RLC and PDCP, each at 100 ms.
- Database writing: OFF; no database credentials are required.

The KPM callback handles indication formats 1 and 3.
UE report indexes identify entries within a report, not persistent UE IDs.
Radio statistics output shows record counts and timestamps.

For other agents, select supported service models, metrics and RAN types.
Unsupported subscriptions may fail inside the native SDK.
Use one xApp process at a time for the initial demo.

## Troubleshooting

- No nodes: check emulator registration in the RIC and agent logs.
- No KPM subscriptions: check the configured RAN type and connected nodes.
- Empty radio records: transport works, but no record data is available.
- SDK import failure: verify the installation and FLEXRIC_SDK_PATH.
- Connection failure: check RIC startup, addresses, SCTP and port conflicts.
- No reports: inspect subscription responses and service-model compatibility.

OAI uses a different embedded FlexRIC revision. These emulator tests do not
establish interoperability with the OAI E2 agent.

## Additional O-RAN scenario demos

| File | Purpose | Input |
| --- | --- | --- |
| xapp_kpm_recorder.py | Record KPM measurements as CSV | Live FlexRIC KPM reports |
| xapp_qos_watch.py | Flag sustained low mean throughput | Live FlexRIC KPM reports |
| xapp_traffic_steering.py | Recommend migration between cells | traffic_samples.json |
| xapp_slice_policy.py | Recommend slice PRB budgets | slice_samples.json |
| xapp_energy_policy.py | Recommend energy-mode changes | energy_samples.json |

The recorder and QoS monitor reuse xapp_kpm.py subscription and shutdown.
Keep these Python files together in this directory.

Traffic steering, slice allocation, and energy saving are standalone
policy prototypes using synthetic JSON inputs. They do not connect to
the RIC or send E2 control requests. Output recommendations are not
executed network actions.

### Additional validation

- Recorder: received format 3 indications, wrote 52 valid CSV records,
  and cancelled its subscription successfully.
- QoS monitor: received live emulator reports and triggered DL/UL alerts
  using a test threshold of 100 and two consecutive low reports.
- QoS logic: alert persistence, recovery, and missing-data reset passed.
- Steering: pending, recommendation, cooldown, and balanced outputs passed.
- Slice allocation: approximately 45/40/15 percent for the supplied scenario.
  Budget limits, unused capacity, and excessive-minimum rejection passed.
- Energy policy: sustained-low-demand, hold, and restoration outputs passed.
  Active-UE, coverage, and sampling-gap checks passed.

All live measurements above came from the FlexRIC emulator.
Actual handover, scheduler changes, energy savings, and OAI integration
have not been validated.

### Run the recorder and QoS monitor

Start the RIC and emulator as described above.
Run from the project root, one xApp at a time:

```bash
XAPP_OUTPUT="/tmp/oai-pi-kpm-$(date -u +%Y%m%dT%H%M%S).csv" \
  timeout --kill-after=5s 30s python3 test/xapp/xapp_kpm_recorder.py \
  -c test/xapp/xapp.conf
```

XAPP_OUTPUT defaults to /tmp/oai-pi-xapp-kpm.csv.
The recorder refuses to overwrite an existing file.
CSV timestamps are UTC receipt times, not agent measurement times.
UE report indexes are local to each indication, not persistent UE IDs.
The recorder retains parent SWIG objects while reading nested reports.
Keep generated CSV files outside Git.

Run the QoS monitor with demonstration thresholds:

```bash
XAPP_QOS_THRESHOLD=100 XAPP_QOS_LOW_REPORTS=2 \
  timeout --kill-after=5s 30s python3 test/xapp/xapp_qos_watch.py \
  -c test/xapp/xapp.conf
```

Defaults: threshold 6, consecutive low reports 3.
The threshold uses the agent-reported measurement units.
Each node/metric is evaluated using the arithmetic mean of valid,
complete, nonnegative measurements in the current indication.
This is not aggregate cell throughput or a per-UE SLA check.
Missing valid measurements reset the consecutive-report counter.
No arriving indications do not trigger a separate stale-data alarm.
Low throughput may indicate idle demand rather than a QoS fault.

### Run the policy prototypes

These commands need only Python 3; no running RIC or SDK is required.
Run from the project root:

```bash
python3 test/xapp/xapp_traffic_steering.py test/xapp/traffic_samples.json
python3 test/xapp/xapp_slice_policy.py test/xapp/slice_samples.json
python3 test/xapp/xapp_energy_policy.py test/xapp/energy_samples.json
```

Run each command separately. JSON sample times are simulation timestamps;
the programs do not wait for those times to elapse.

#### Traffic steering

Input: strictly increasing time_s and a cells map of comparable normalized
loads in [0, 1]. Do not substitute throughput values for normalized load.

Recommend considering UE migration when the highest-load cell is at least
0.8, the lowest-load cell is at most 0.6, and the gap is at least 0.2.
The same source/target pair must qualify in two consecutive samples.
Recommendations have a global 30-second cooldown.
Sample spacing is not validated for freshness.
The balanced status means no candidate meets these thresholds;
it does not guarantee equal loads.

Coverage, UE eligibility, target capacity, and control support must be
checked before implementing an actual handover.

#### Slice allocation

Input: unique slice_id, min_prb_percent, demand_prb_percent, and priority.
Minimum budgets must total no more than 100 percent.
Allocate minimum budgets first, then distribute remaining capacity using
unmet demand weighted by priority, capped at each slice's demand.
A minimum budget is retained even when demand falls below that minimum.
Unused capacity is reported when all demands are satisfied.
Floating-point results may contain small representation differences.

Slice names are illustrative labels, not configured S-NSSAI values.
Demand estimates and scheduler-specific E2 controls require integration.

#### Energy saving

Input: increasing time_s, demand_ratio in [0, 1], observed_mode,
active_ues, and neighbor_coverage_confirmed.

For an active cell, demand must remain at most 0.2 for 30 seconds,
with no active UEs and confirmed neighbor coverage.
Gaps greater than 15 seconds reset the low-demand timer.
In energy_saving mode, demand at least 0.6, any active UE, or lost
coverage confirmation produces a restoration recommendation.
Observed mode changes must come from input; recommendations do not change it.
Recommendations may repeat while their conditions remain true.

Demand in a reduced-power state must come from an appropriate external
observation or estimate. These samples do not measure power consumption.

## Slice control through the lab emulator

xapp_slice_control.py converts slice policy budgets into custom
SLICE service-model ADD/MOD control using NVS capacity fractions.

With the RIC and emulator running, execute from the project root:

```bash
timeout --kill-after=5s 20s python3 test/xapp/xapp_slice_control.py \
  -c test/xapp/xapp.conf
```

The default input is slice_samples.json beside the script.
Set XAPP_SLICE_INPUT to select another input file.
The demo requires positive budgets and uniquely selects a connected gNB
with PLMN 505/01. XAPP_SLICE_NODE_ID selects the node and defaults to 1.
The accepted lab ID range is 1..65535; invalid IDs are rejected before
RIC initialization. Missing or ambiguous targets receive no control.
Verify that the selected node is the lab emulator.

Multi-Agent and multi-RIC validation is documented in
[the slice-control guide](../flexric/README.slice-control.md).

### Validation on Raspberry Pi

- Constructed capacity fractions 0.45, 0.40, and 0.15.
- The emulator logged SLICE CONTROL ADD rx.
- The emulator logged CONTROL ACKNOWLEDGE tx.
- The xApp received CONTROL ACK and returned to the shell.

This validates control-message delivery and acknowledgment.
The emulator does not apply or retain scheduler changes.
NVS capacity fractions do not demonstrate enforced PRB allocation.
The demo uses FlexRIC's custom SLICE model, not O-RAN E2SM-RC.
OAI scheduler integration remains unvalidated.

Redirected emulator output may be buffered. For subsequent tests,
start the emulator with line-buffered output:

```bash
stdbuf -oL -eL /usr/local/bin/flexric/e2agent/emu_agent_gnb \
  -c /usr/local/etc/flexric/e2agent.conf \
  > /tmp/oai-pi-xapp-agent.log 2>&1 &
DEMO_AGENT_PID=$!
```

Start this command only when the previous demo agent has stopped.

## E2SM-RC handover control communication demo

xapp_handover_control.c is adapted from the vendored FlexRIC
two-e2-nodes-two-cells/xapp_rc_ctrl_ho.c example.
The upstream license notice is retained.

This lab demo sends RC control style 3, action 1, using header and
message format 1. It targets exactly one connected node with
PLMN 505/1 and node ID 1. Verify that this node is the lab emulator.

### Build

Run from the project root:

```bash
cmake -S flexric -B flexric/build-local -DBUILD_OAI_PI_XAPP_DEMOS=ON
cmake --build flexric/build-local --target xapp_handover_control --parallel 2
```

Run each command separately.
The optional CMake integration is disabled by default.
The binary remains under flexric/build-local/oai-pi-xapp/.

### Run

Start the RIC and emulator as described above.
Use line-buffered logging for both processes.

```bash
XAPP_RAN_UE_ID=1 XAPP_SOURCE_NR_CGI=256 XAPP_TARGET_NR_CGI=512 \
  timeout --kill-after=5s 20s \
  flexric/build-local/oai-pi-xapp/xapp_handover_control \
  -c test/xapp/xapp.conf
```

All three environment variables are required unsigned decimal integers.
UE IDs are parsed as 64-bit values; CGI inputs are limited to 36 bits.
Source and target must differ.
The demo assumes a 28-bit gNB ID and extracts it from the source CGI.
The sample source CGI 256 therefore selects node ID 1.

These are synthetic identifiers. The UE identity retains the upstream
example's placeholder GUAMI. The target CGI payload retains its
decimal-string representation for compatibility with this emulator.
This is not validated as interoperable NR CGI encoding for a real RAN.

### Validation and limitations

Validated on Raspberry Pi:
- Native compilation succeeded.
- The xApp received CONTROL ACK and stopped normally.
- The emulator logged UE ID 1 and target NR CGI 512.
- The emulator logged CONTROL ACKNOWLEDGE tx.
- Negative, overflowing, nonnumeric, and identical-cell inputs were rejected
  before SDK initialization.

An initial run timed out waiting for a response and triggered an SDK
assertion. A fresh RIC and emulator run succeeded; the cause of the
initial failure remains unresolved.
An executable-stack linker warning remains.

The emulator parses the request and acknowledges it without performing
handover. The target cell need not exist for this communication test.
Actual UE migration, traffic changes, and OAI integration are unvalidated.
xapp_steering_control.py connects synthetic steering recommendations to this communication demo.

## Steering policy to emulator control

xapp_steering_control.py reuses SteeringPolicy from xapp_traffic_steering.py.
It validates the complete input, selects the first recommendation,
maps cell names through steering_lab.json, and optionally invokes
the compiled xapp_handover_control demo.

Default lab mapping:
- UE ID: 1.
- cell-a: CGI 256, selecting source gNB ID 1.
- cell-b: CGI 512, used as a synthetic target.

### Run

Run from the project root. The default mode needs only Python:

```bash
python3 test/xapp/xapp_steering_control.py
```

Expected selection: time_s 1, cell-a to cell-b, CGI 256 to 512.
Dry-run mode does not connect to the RIC or invoke the native binary.

For control communication, build xapp_handover_control first and start
the lab RIC and emulator as described above. Then run:

```bash
python3 test/xapp/xapp_steering_control.py --send-emulator
```

Each invocation sends at most one request.
The program does not wait for sample timestamps to elapse.
The policy's cooldown uses simulation time, not wall-clock time.
Repeated invocations reset policy state and may send the same request again.

Optional arguments:
- Positional input: JSON load samples; defaults to traffic_samples.json.
- --mapping: cell/UE mapping; defaults to steering_lab.json.
- --config: SDK configuration; defaults to xapp.conf.
- --binary: compiled handover demo path.

Defaults are resolved relative to the script and project directories.
The child control process has a 20-second timeout.
Failure or timeout produces a nonzero exit; inspect RIC and agent logs.

### Validation on Raspberry Pi

- Dry run selected the first qualifying recommendation.
- Balanced input produced no request.
- Invalid later loads, unmapped cells, and nonincreasing times were rejected.
- Emulator mode received CONTROL ACK and exited normally.
- The agent logged one handover request with UE ID 1 and target CGI 512,
  followed by CONTROL ACKNOWLEDGE tx.

The executed=false field denotes that actual UE migration is not performed.
Input loads, UE identity, and target cell are synthetic.
There is no live load acquisition or post-control measurement feedback.
This validates policy-to-control communication, not closed-loop balancing,
actual handover, or OAI interoperability.

## Energy policy with simulated mode feedback

xapp_energy_simulator.py reuses EnergyPolicy and maintains an in-memory
cell mode. Recommendations update that simulated mode, which becomes
the observed_mode used for the next policy evaluation.

Run from the project root:

```bash
python3 test/xapp/xapp_energy_simulator.py
```

The default input is energy_samples.json beside the script.
A positional argument selects another observation file.
Use --initial-mode active or --initial-mode energy_saving to select
the simulator's starting mode; the default is active.

Original observations are validated before replay.
Their observed_mode values are retained as input_observed_mode for
comparison, but the replay uses the simulator's own mode.
Demand, active UE counts, and coverage confirmation remain external
input values. Mode changes do not alter those values.

Each output includes simulation_mode_before, simulation_mode_after,
and applied_in_simulation. The executed field remains false because
no real device action occurs.

### Validation on Raspberry Pi

- Entered simulated energy-saving mode at time_s 30.
- Retained that mode at time_s 40.
- Restored active mode at time_s 50.
- Mode feedback worked even when all original input modes were active.
- Active UEs, missing coverage, and excessive sampling gaps prevented
  entry into energy-saving mode.
- Active UEs or lost coverage caused restoration from energy-saving mode.

This program requires only Python; it does not connect to a RIC or
send E2 controls. Simulation timestamps do not cause real-time delays.
The model assumes immediate successful mode changes without hardware
latency or failure. State is reset on each invocation.

No energy-control handler was identified in the inspected emulator code.
Real cell activation, RF operation, power consumption, energy savings,
and OAI integration remain unvalidated.

## Automated emulator regression tests

Run from the project root after building and installing FlexRIC and
building xapp_handover_control:

```bash
bash test/xapp/run-emulator-tests.sh
```

The runner requires the installed local RIC and emulator configurations
to use 127.0.0.1. It refuses to start when an existing lab RIC or emulator
is detected.

Each case starts a fresh RIC and emulator, waits for startup and E2
registration, runs one xApp with a timeout, and stops its child processes.
Cleanup also runs on failure or interruption, with bounded shutdown waits.
Logs and the recorded CSV are retained in a unique directory under /tmp
by default, or under TMPDIR when set.

### Validation on Raspberry Pi

All seven cases passed:
- Connected-node listing.
- KPM DL and UL measurement reporting.
- MAC, RLC, and PDCP callbacks.
- KPM CSV recording: 52 valid measurements in the observed run.
- Sustained-low-throughput DL and UL alerts.
- Custom SLICE control delivery and acknowledgment.
- Steering recommendation mapped to E2SM-RC handover control.

Final checks passed for callback errors, subscription delete responses,
exactly one request per control case, and agent/xApp acknowledgments.
No RIC or emulator processes remained after the run.

CSV row counts can vary with emulator indications. The runner checks
nonempty records, expected metrics, node identity, and finite values;
it does not require exactly 52 rows.

This suite validates emulator reporting and control communication.
It does not validate actual UE handover, scheduler enforcement,
energy savings, or OAI interoperability.
