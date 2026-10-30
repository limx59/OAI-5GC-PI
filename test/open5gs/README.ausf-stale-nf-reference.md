# AUSF stale NF reference and real UE validation

## Status and scope

Passed on Raspberry Pi ARM64 with Open5GS v2.7.2:

- Isolated Docker Compose regression using real original/patched AUSF binaries:
  original port-omission defect reproduced; three patched deregistration and
  registration cycles passed.
- Patched AUSF with a real OCUDU/OAI UE session: `oaitun_ue1` obtained
  `192.168.100.146`; two TUN-bound UPF ping checks each received 5/5 replies,
  separated by a 20-second wait.
- Test containers were removed. Baseline core service identities remained
  unchanged during both formal validators.

The isolated test uses synthetic SBI peers and a deliberate HTTP 500 response.
It validates routing and cached-reference invalidation, not successful AKA.
The real UE test separately validates session establishment and connectivity.

Actual NRF heartbeat-loss recovery, long-term stability, physical RF and
dual-node steering recommendations are not established by these results.

## Failure mechanism and patch

The observed AUSF request to SCP contained
`3gpp-sbi-target-apiroot: http://172.22.0.13`, without `:7777`.
SCP consequently attempted HTTP port 80. UDM configuration, listener and
the NRF-advertised service endpoint all specified port 7777.

AUSF UE contexts retained raw NF-instance references after peer removal.
Cached-reference lookup did not check live-list membership. When service
and version lookup failed, `ogs_sbi_client_find_by_service_name()` fell back
to the NF-instance client. Its HTTP instance address could produce an API root
without an explicit port. Upstream error handling retained the UE context,
allowing subsequent requests to reuse the stale reference.

`patches/patch-ausf-stale-nf-reference.py` adds AUSF-local invalidation.
It compares cached pointers against live NF instances without dereferencing
stale objects, clears missing references and validity timeouts, and repeats
checks around notification/FSM dispatch and before new requests.
Fresh discovery can then select the advertised service endpoint.

The patch does not hardcode port 7777 or change global HTTP defaults.
It is applied only to disposable container build sources.
Existing third-party source trees are preserved.
These tests do not prove all possible object-pool reuse or NF lifecycle paths.

## Delivery files

| Purpose | Entry |
| --- | --- |
| Patch | `patches/patch-ausf-stale-nf-reference.py` |
| Review-local build | `build-ausf-stale-nf-reference-v2.py` |
| Isolated routing validator | `validate-ausf-stale-nf-reference-v2.py` |
| Real UE validator | `validate-ausf-real-ue.py` |
| Routing Compose | `../../deploy/open5gs/compose.ausf-stale-nf-reference-v2.yaml` |
| Real UE Compose | `../../deploy/open5gs/compose.ausf-real-ue.json` |
| Bounded gNB configuration | `../../deploy/open5gs/config/gnb-ausf-validation.yml` |
| AUSF image override | `../../deploy/open5gs/compose.ausf-published.override.yaml` |

## Image identity

ARM64 image references used for reproducibility:

- AUSF: `limx59/open5gs-ausf:arm64-stale-nf-reference-test@sha256:7ba6049f69cde00ba19eb19319020ea7d3d078b040bd0ecf122398f8fa96f3c4`
- HTTP/2 fixture: `limx59/open5gs-ausf-tests:arm64-stale-nf-reference-test@sha256:937d3daf3a33dba7a9d6a3cfabe52288cc7d3eb0c1c257a9999beca901ca4eb1`

The control image is the locally retained `docker_open5gs:local-arm64`,
with ID `sha256:69d576e04d6e5a094b8c0e37e69bc1ba173dfa23bbfaf4de712f5959b5f04edd`.
The isolated validator checks this identity independently of the active AUSF.
A clean machine needs this original control image separately.

## Build

Run from the repository root. The build requires clean Open5GS revision
`6d91a793af25ee36dc4662755843192177ee412b` in `open5gs/`
and the reviewed original local runtime image.

Compilation runs inside Docker with `BUILD_JOBS=2`.
Only the patched AUSF executable is copied into the runtime.

```bash
python3 -B test/open5gs/build-ausf-stale-nf-reference-v2.py
```

Build evidence and temporary snapshots stay under
`test/open5gs/.local/evidence/`.
New build output must be validated before deployment.

## Run isolated routing regression

Both published images and the original control image must be locally available.
The validator uses a unique Compose project and an internal network without
published ports. It does not replace the active AUSF.

```bash
python3 -B test/open5gs/validate-ausf-stale-nf-reference-v2.py
```

Expected results:

- Original target loses its port after deregistration.
- Patched target is absent while requesting fresh `nudm-ueau` discovery.
- After registration, the patched target returns to
  `http://192.0.2.13:7777`, for three cycles.

## Run real UE validation

Prerequisites:

- Patched AUSF is already active. This validator checks its image identity
  but does not deploy or replace it.
- Core services `ausf`, `udm`, `udr`, `nrf`, `scp`, `amf`, `smf`, `upf`
  are running on `docker_open5gs_default`.
- Addresses `172.22.0.160` and `172.22.0.161` are free.
- Private UE configuration exists at `deploy/ocudu/.local/ue-zmq.conf`,
  with matching subscriber provisioning in the core.
- OAI UE capability XML and pinned gNB/UE images are locally available.
- `/dev/net/tun` and sufficient host resources are available.

```bash
python3 -B test/open5gs/validate-ausf-real-ue.py
```

The gNB configuration uses 65536 buffer segments.
UE credentials are mounted read-only and excluded from delivery files.
The validator waits for the tunnel, performs both UPF checks, verifies core
continuity and removes only its own gNB/UE Compose project.

The AUSF image override must be combined with reviewed base Compose files
and suitable separate runtime mounts. It is not a standalone deployment
and does not reproduce private subscriber provisioning.

## Evidence

Formal routing evidence:

`test/open5gs/.local/evidence/ausf-stale-nf-routing-54qh1tof/`

Formal real UE evidence:

`test/open5gs/.local/evidence/real-ue-0afzsmoi/`

Validators retain JSON summaries and diagnostics.
Keep private runtime logs local; do not commit credentials, captures or evidence.

## Troubleshooting history

- Initial dual-node runs encountered host OOM before buffer pools were bounded.
- A copied AUSF startup script had mode 600 and exited 126.
  A new executable copy corrected startup without changing original files.
- Compose exported zero-valued core ulimits as empty objects.
  The formal real UE Compose explicitly uses `core: 0`.
- The fixture check container required the evidence owner's UID/GID.
- Initial scripts used workstation-specific or random paths.
  Formal entries use repository-relative configuration, unique projects
  and review-local evidence.

## Remaining

- Actual NRF heartbeat-loss and recovery validation.
- Broader Docker Compose end-to-end workflow audit.
- Resource-permitting dual-node steering remains a separate OCUDU case.
