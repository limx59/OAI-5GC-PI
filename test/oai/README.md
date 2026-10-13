# OAI gNB to FlexRIC KPM interoperability test

This test runs an OAI gNB with RF simulation, connects it to an existing
Open5GS AMF, and verifies E2 registration and KPM subscription lifecycle.
Run commands from the project root unless stated otherwise.

## Components and versions

- OAI gNB: E2 agent enabled, E2AP V2, KPM V3.00.
- Near-RT RIC and Python xApp SDK: standalone FlexRIC, E2AP V2, KPM V3.00.
- gNB service-model plugin: built from OAI's embedded FlexRIC source.
- RF simulation: no physical radio required for this test.

Matching protocol versions alone do not establish compatibility between
different FlexRIC source revisions. Keep the gNB plugin built from the
same embedded source as the gNB.

## Build and prepare

The project build wrapper defaults to KPM_V3_00 when E2 is enabled:

```bash
bash scripts/build-oai.sh gnb
```

OAI_KPM_VERSION can explicitly select KPM_V2_03 or KPM_V3_00.
This test requires KPM_V3_00 and E2AP_V2.

Build the shared KPM plugin separately:

```bash
cmake --build oai/cmake_targets/ran_build/build --target kpm_sm --parallel 2
```

Prepare the isolated plugin directory:

```bash
python3 test/oai/prepare-kpm-plugins.py
```

The helper checks the cached E2 settings and copies libkpm_sm.so into
the build directory's e2-sm-plugins-kpm directory. It rejects additional
entries in that destination. It does not build or install libraries.

## SDK S-NSSAI encoding

The Python SDK's KPM format 4 subscription now encodes its fixed S-NSSAI
condition as a one-byte OCTET STRING: SST 1, without SD.
The previous integer condition caused OAI to abort in capture_sst_sd().

Rebuild the changed SDK:

```bash
cmake --build flexric/build-local --target xapp_sdk --parallel 2
```

For the validated Raspberry Pi Python installation, update the module:

```bash
sudo install -m 755 flexric/build-local/src/xApp/swig/_xapp_sdk.so \
  /usr/local/lib/python3/dist-packages/xapp_sdk/_xapp_sdk.so
```

The emulator adapter accepts the OCTET STRING condition and retains the
legacy integer path. Its dummy predicate uses SST only and does not
model real slice membership or SD matching.

Rebuild and update the gNB emulator before running emulator regressions:

```bash
cmake --build flexric/build-local --target emu_agent_gnb --parallel 2
```

```bash
sudo install -m 755 flexric/build-local/examples/emulator/agent/emu_agent_gnb \
  /usr/local/bin/flexric/e2agent/emu_agent_gnb
```

## Local test configuration

gnb-e2-rfsim.conf and neighbour-config-rfsim.conf are adapted/copied from
the vendored OAI RF-simulation examples. Their license notices are retained.

The supplied configuration uses this existing lab network:

| Setting | Value |
| --- | --- |
| AMF address | 172.22.0.10 |
| Host N2/N3 address | 172.22.0.1/24 |
| gNB GTP-U port | 2153 |
| RIC address | 127.0.0.1 |
| E2 SCTP port | 36421 |
| xApp E42 SCTP port | 36422 |
| PLMN | 001/01, two-digit MNC |
| TAC / SST | 1 / 1, no SD |
| gNB ID | 3584 |
| NR cell ID | 12345678 |
| RF simulator port | 4043 |

These addresses must match the deployment. They are not universal defaults.
The host reaches the existing AMF through its Docker bridge.
This test does not change the existing core or UERANSIM containers.

The configuration includes the neighbor file beside it and uses
sm_dir="./e2-sm-plugins-kpm/". Launch the gNB from its build directory.

## Run

Use separate terminals. First verify that no previous test RIC, emulator,
or OAI gNB is running.

Terminal 1, start the RIC in the foreground:

```bash
stdbuf -oL -eL /usr/local/bin/flexric/ric/nearRT-RIC \
  -c /usr/local/etc/flexric/ric.conf
```

Terminal 2, from the project root, start the gNB with a bounded runtime:

```bash
sudo bash -c '
  cd "$1/oai/cmake_targets/ran_build/build" &&
  ulimit -c 0 &&
  ulimit -l unlimited &&
  exec timeout --signal=INT --kill-after=5s 600s \
    stdbuf -oL -eL ./nr-softmodem \
    -O "$1/test/oai/gnb-e2-rfsim.conf" --rfsim
' bash "$PWD"
```

The per-process unlimited memlock setting resolved an allocation failure
observed with the regular user's approximately 1 GiB memlock limit.
No persistent host limit changes are required by these instructions.

Wait for E2 SETUP RESPONSE rx before running the xApp in terminal 3:

```bash
timeout --kill-after=5s 30s python3 test/xapp/xapp_kpm.py \
  -c test/xapp/xapp.conf
```

Stop the foreground gNB and RIC with Ctrl-C when finished.
The gNB also has a 600-second timeout.

Use SA mode with --rfsim for this test. Do not add --phy-test:
the current monolithic E2 setup implementation waits for captured NGAP
Setup Request/Response messages, while phy-test mode disables NGAP setup.

## Verified on Raspberry Pi

- The gNB loaded the matching KPM plugin through its relative path.
- E2 Setup Request/Response completed.
- The node-listing xApp identified gNB 3584, MCC 1, MNC 1.
- KPM format 4 subscription succeeded.
- OAI decoded the condition as NSSAI (1, ffffff), indicating no SD.
- Subscription deletion completed normally.
- OAI reported that no UE matched the condition.
- All seven emulator regression cases passed after the SDK and emulator
  changes, including CSV validation and control acknowledgments.

No KPM throughput reports were received in this OAI test because no
matching UE was present. UE registration, user traffic, throughput
measurement, and handover remain unvalidated for this setup.

## Compatibility limits

Loading the standalone service-model plugins into this OAI build caused
an RC encoder assertion. Loading matching embedded plugins resolved that
failure, but the standalone xApp SDK still rejected the embedded RC RAN
function definition with an unsupported ranParameter_Definition assertion.

This configuration therefore exposes KPM only. RC interoperability remains
unresolved; do not use the emulator handover or slice-control demos as
evidence of OAI control compatibility.

Generated ASN.1 compiler warnings and executable-stack linker warnings
remain. Independent-container E2 registration and KPM subscription
lifecycle have also been validated using published ARM64 images.
See [the container deployment guide](../../deploy/oai-flexric/README.oai.md).
OAI RFSim UE registration, user-plane traffic and UE KPM reporting were
subsequently validated; see
[the end-to-end guide](../../deploy/oai-flexric/README.e2e.md).
RC control remains unvalidated.
