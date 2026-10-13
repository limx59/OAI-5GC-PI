# Experimental OAI E2 RC-triggered N2 handover

Validated on ARM64 Raspberry Pi on 2026-10-11, Pacific time.

This guide records the original forward-only validation.
See [UE handover and closed-loop feedback](README.oai-n2-closed-loop.md)
for the 2026-10-12 bidirectional, actual-MAC-rate-driven extension,
NCC rollover correction, published images and ICMP observations.
These dedicated test images are not replacements for the regular images.

## Validated scope

One RFsim UE runs as server at 172.29.0.32. Two gNBs connect as clients.
Source: E2 node 3584, NR cell 12345678, PCI 0.
Target: E2 node 2816, NR cell 720898, PCI 1.
Both use PLMN 00101, 24 PRB and numerology 1, with SSB bitmaps 1 and 2.

The xApp queries RC Report Style 5 for the actual UE context and neighbours.
With OAI_N2_CONTROL_TEST=1, it sends one Control Style 3 handover request
only after checking the source context and target neighbour.
The target NR CGI is encoded as an eight-byte OCTET STRING.

Validation checks target RRC handover completion and NGAP Handover Notify,
target PDU session establishment, removal of the source UE, unchanged UE
IPv4 address, five successful post-handover pings, subscription deletion
and unchanged identities of RIC, both gNBs and UE during the control phase.
Containers are recreated to establish each round's baseline.

Manual and single automated validation passed. Dedicated CPU allocation
passed one round, then three local-image and three published-image rounds.
Published evidence: regression-hstopmas.
Archive: oai-n2-handover-regression-20261011-223157-regression-hstopmas.tar.gz
under ~/Work/oai-test-evidence/.

## SDK and scheduling requirements

Use the OAI embedded FlexRIC SDK for both RIC and xApp.
The regular standalone SDK has an unimplemented neighbour-table decoder:
the original RIC aborted when it received this report.
The dedicated SDK uses INI configuration and SQLite, unlike the regular
lab xApp configuration. Do not mix its plugins with the regular SDK.

prepare-oai-ue-context.py changes only the copied /src/flexric/examples
build entry inside Docker. Repository OAI and FlexRIC sources are unchanged.

All three RAN processes initially shared CPUs 1-3. Baseline packet loss
occurred in two automated attempts, including the first regression round;
those failures were retained. Separate container CPU sets use source 1,
target 2 and UE 3. The first allocated-CPU run had average RTTs of 24.1 ms
(single cell), 33.5 ms (two cells) and 30.7 ms (after handover).
This comparison supports a scheduling hypothesis, not a fully isolated
root-cause claim. No host affinity, firewall or sysctl changes are required.

## Published images

| Component | Image | Validated image-index digest |
| --- | --- | --- |
| gNB | `limx59/oai-pi-oai-gnb:arm64-rc-handover-test` | `sha256:64bca8439d993adf483528ece58c95b29b8096a4dec422fc5631a896e169243b` |
| RIC | `limx59/oai-pi-flexric-ric:arm64-oai-rc-test` | `sha256:b5503f6a97ecd486cfe145a31f0ce1880bd46a8e44478fe902a07f335c36f839` |
| xApp | `limx59/oai-pi-flexric-xapp:arm64-oai-ue-context-test` | `sha256:d61ccd76ce90b6258dc73139663fcede239eb19590a83e085525e0f5b7e9570b` |

Tags are mutable. Index digests differ from runtime image IDs.
The existing UE image remains limx59/oai-nr-ue:arm64.

## Prerequisites and reproduction

Run from the repository root. Use the existing Open5GS core and provisioned
local UE configuration described in [the end-to-end guide](../../deploy/oai-flexric/README.e2e.md).
The external lab and core networks and required addresses must be free.
Keep UE authentication material local.

Pull the dedicated images:

```bash
sudo docker pull limx59/oai-pi-oai-gnb:arm64-rc-handover-test
sudo docker pull limx59/oai-pi-flexric-ric:arm64-oai-rc-test
sudo docker pull limx59/oai-pi-flexric-xapp:arm64-oai-ue-context-test
```

Define the complete Compose set:

```bash
compose=(sudo docker compose \
  -f deploy/oai-flexric/compose.oai.yaml \
  -f deploy/oai-flexric/compose.oai-radio-stats.yaml \
  -f deploy/oai-flexric/compose.oai-n2-handover.yaml \
  -f deploy/oai-flexric/compose.oai-rc-sdk.yaml \
  -f deploy/oai-flexric/compose.oai-n2-cpu-isolated.yaml)
"${compose[@]}" --profile ue --profile tools config --quiet
```

The validators reset only this OAI experiment project. Do not run them
while that project contains other active work. They establish RIC, source
gNB, attached UE, then target gNB, and leave services running afterwards.
A failure also retains services for diagnosis; temporary xApps are removed.

```bash
python3 test/flexric/validate-oai-n2-handover.py \
  --compose-overlay deploy/oai-flexric/compose.oai-n2-cpu-isolated.yaml \
  --output-dir /tmp/oai-n2-handover-auto </dev/null
```

Run the three-round wrapper, which stops on failure and archives evidence:

```bash
python3 test/flexric/validate-oai-n2-handover-regression.py \
  --compose-overlay deploy/oai-flexric/compose.oai-n2-cpu-isolated.yaml \
  --output-dir /tmp/oai-n2-handover-regression </dev/null
```

Review summary.json and all round summaries. An ACK alone is insufficient.
The xApp defaults to query-only; do not repeat a control request after a
timeout without inspecting the current UE state.

## Boundaries

This verifies forward N2 mobility with state and data-plane feedback.
It does not validate load-driven policy, reverse handover, interruption
time, sustained throughput, production availability or general SDK
compatibility across the original Emulator test cases.
Two simultaneous UE sessions and measured multi-cell load remain
unvalidated; this one-UE mobility topology does not resolve that case.

## Cleanup

Save evidence before removing containers:

```bash
"${compose[@]}" --profile ue stop --timeout 15 nrue gnb gnb-2
"${compose[@]}" --profile ue --profile tools down --remove-orphans
```

Verify removal:

```bash
sudo docker ps -a \
  --filter label=com.docker.compose.project=oai-pi-oai-e2-lab \
  --format 'table {{.Names}}\t{{.Status}}'
```

Open5GS, external networks, images, subscribers and local credentials remain.
