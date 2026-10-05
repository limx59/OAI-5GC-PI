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
