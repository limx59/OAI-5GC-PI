# OCUDU E2 build configuration and FlexRIC compatibility validation

## Purpose and scope

Verify the existing ARM64 builder configuration and configured gNB E2
link dependencies, then validate the current patched runtime image
combination through the existing DU KPM integration test.

Completed on 2026-10-19, Pacific time. No new image was built.

The result applies to the documented DU KPM subset. Protocol declarations
differ between the implementations; this is not a full conformance test.

## Prerequisites

Run from the repository root:

```bash
cd ~/Work/oai-5gc-pi-review
```

The build check requires Docker access and the existing local ARM64 image:

```text
limx59/oai-pi-ocudu-kpm-tests:arm64-clock-selection
```

The integration check additionally requires the existing Open5GS deployment,
UE configuration, baseline RIC and available temporary RIC address.
Follow the prerequisites in
[the delete-rejection guide](README.kpm-delete-rejection.md).
The experimental gNB and UE must be stopped before that check.

## Build-configuration check

Run the retained validation script:

```bash
python3 -B test/ocudu/validate-e2-build-config.py
```

The script inspects the local image identity and ARM64 architecture,
checks CMakeCache.txt, and queries the configured gnb_split_8 link command
with Ninja. It does not compile or start the RAN.

| Checked cache entry | Expected value |
| --- | --- |
| CMAKE_BUILD_TYPE | Release |
| BUILD_TESTING | ON |
| ENABLE_ZEROMQ | ON |
| ENABLE_EXPORT | ON |
| ENABLE_PLUGINS | OFF |
| MCPU | cortex-a76+crypto |
| MARCH | armv8.2-a |
| CMAKE_HOME_DIRECTORY | /src/ocudu |

The configured gNB link command must contain both libocudu_e2.a and
libe2ap_asn1.a. This checks the build graph, not the final runtime binary.

Evidence is saved under ~/Work/oai-test-evidence/ocudu-e2-build-config-*,
including summary.json, check.stdout and check.stderr.

## Runtime interoperability check

Use the existing validator:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  test/ocudu/validate-kpm-delete-rejection.py </dev/null
```

The validator uses these published tags:

| Component | Image |
| --- | --- |
| gNB | limx59/oai-pi-ocudu-gnb:arm64-kpm-delete-rejection-test |
| RIC | limx59/oai-pi-ocudu-flexric-ric:arm64-delete-rejection-test |
| xApp | limx59/oai-pi-ocudu-flexric-xapp:arm64-delete-rejection-test |

It exercises DU E2 setup and discovery as prerequisites, normal KPM
subscription/reporting, an explicitly injected delete rejection,
continued reports, successful retry and post-delete silence.

The injection is enabled only by the test configuration. The validator
retains evidence, restores the original RAN configuration and stops the
experimental RAN. It checks that the baseline RIC identity is unchanged.

## Recorded results

| Check | Result | Evidence directory under ~/Work/oai-test-evidence/ |
| --- | --- | --- |
| ARM64 builder cache and E2 link dependencies | Passed; no cache mismatches | ocudu-e2-build-config-5meognva |
| Current runtime image combination | Passed | ocudu-kpm-delete-rejection-9_touixy |

The integration run recorded:

- Five initial reports.
- Five reports after the rejected deletion grace period.
- Exactly one injected rejection, one delete failure and one delete response.
- Successful retry using the same subscription.
- Approximately six seconds of post-grace sender/callback observation,
  with no late sends or callbacks.
- No callback or cleanup errors.
- Baseline RIC unchanged; original RAN configuration restored and stopped.

Recorded image identities are retained in the evidence summaries.
Use the tags above for execution.

## Source and configuration audit

OCUDU lib/CMakeLists.txt includes the e2 directory.
lib/e2/CMakeLists.txt defines ocudu_e2 and links e2ap_asn1.
lib/asn1/CMakeLists.txt includes E2AP and KPM ASN.1 sources in that library.
apps/gnb/CMakeLists.txt references these E2 libraries and generates the
gnb_split_8 target. The actual configured link command confirmed both
libraries.

The inspected inclusion path does not require an additional ENABLE_E2
switch. Runtime activation is separate from library inclusion.

The runtime configuration enables DU E2 and KPM, disables CU-CP/CU-UP E2,
RC and CCC, enables RLC metrics, and sets du_report_period to 1000 ms.
The baseline RIC is 172.22.0.162:36421; the rejection validator temporarily
uses 172.22.0.163.

## Protocol declarations and compatibility boundary

| Item | OCUDU declaration | FlexRIC selection |
| --- | --- | --- |
| E2AP | e2ap.h labels v03.00 | E2AP_V3; inspected implementation directory v3_01 |
| KPM ASN.1 | e2sm_kpm_ies.h labels E2SM v05.00 | KPM_V3_00 |

These labels do not match exactly. Successful procedure completion
establishes interoperability for the exercised subset, not equivalence
of the complete schemas.

OCUDU advertises ORAN-E2SM-KPM, function ID 2, revision 0 and OID
1.3.6.1.4.1.53148.1.2.2.2. Revision and OID alone do not prove protocol
version equivalence.

The source conditionally constructs report-style entries 1 through 5.
The completed traffic/idle validation covers Style 1/4; the source
declarations do not establish validation of the other styles.

## Related validation and implementation

- [Normal DU KPM/CSV workflow](README.zmq-kpm.md)
- [One-second monitoring](README.kpm-one-second.md)
- [Subscription rejection and recovery](README.kpm-subscription-rejection.md)
- [Delete rejection and retry](README.kpm-delete-rejection.md)
- [xApp disconnection](README.zmq-kpm-disconnect.md)
- [OCUDU source record](../../docker/ocudu/UPSTREAM.md)
- [FlexRIC build](../../docker/ocudu/Dockerfile.flexric-delete-rejection)
- [gNB build](../../docker/ocudu/Dockerfile.kpm-delete-rejection-test)
- [Runtime configuration](../../deploy/ocudu/config/gnb-zmq-e2.yml)

The build check and runtime integration check are separate scripts.
The runtime test uses patched images; these results do not establish
equivalent behavior for unpatched upstream code.

CU E2, RC/CCC, other report styles and full protocol conformance are
outside this completed validation scope.
