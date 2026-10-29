# Traffic steering policy: common metrics and cooldown rules

## Status and scope

Passed for retained OAI/OCUDU throughput CSV conversion and controlled
normalized-load fixtures against the unchanged shared steering policy.
The dedicated published image, Compose service and fixed host validator
were exercised together.

This is retained-evidence and policy-rule validation. It does not validate
simultaneously online nodes, live dual-node recommendations or E2 control.

## Common metric representation

Both systems export DRB.UEThpDl and DRB.UEThpUl in kbps. The adapter
converts these values to bit/s while preserving direction, system, node,
source semantics and time-association basis.

| System | Source basis | Time basis |
| --- | --- | --- |
| OAI | RLC PDU byte delta / configured granularity | Receipt time |
| OCUDU | RLC provider mean throughput | Nominal KPM window |

Throughput is not normalized cell utilization. Converted records explicitly
set normalized_cell_load to null and eligibility for the normalized-load
policy to false. No capacity reference is inferred from offered traffic.

PRB values have no common mapping in this test. Incorrect units, invalid
values, incomplete rows, wrong identities, unsupported metrics and invalid
timestamps are rejected. OCUDU conversion and nominal windows are checked.

## Policy rules

The existing test/xapp/xapp_traffic_steering.py is packaged unchanged.

Controlled fixtures check source load >= 0.8, target load <= 0.6 and
a load difference >= 0.2. Two consecutive qualifying observations are
required. Balanced input resets candidate confirmation. The 30-second
cooldown applies across both recommendation directions.

Checks cover pending/recommendation/cooldown transitions, reversal,
the 30-second boundary, eligibility boundaries, invalid loads and
non-increasing timestamps. Recommendations remain advisory: executed=false.

The controlled normalized-load fixtures are separate from the converted
real throughput records. They are not simultaneous live-node evidence.

## Reproduce

Use the CSV files retained by the
[sequential OAI/OCUDU comparison](README.steering-sequential-comparison.md).
No RAN or RIC startup is required.

Pull the published, digest-verified linux/arm64 image:

```bash
sudo docker pull limx59/oai-pi-ocudu-flexric-xapp:arm64-steering-common-metrics-test@sha256:03896a15ca9448c1613f66a9196e4bd265c0ec4965817b1096dcb9bc7b36c40b
```

From the repository root, run the fixed Compose validator with the
appropriate retained input paths:

```bash
python3 -B test/ocudu/validate-steering-common-metrics-compose.py   --oai-csv "$HOME/Work/oai-test-evidence/oai-steering-load-h898l24_/kpm.csv"   --ocudu-csv "$HOME/Work/oai-test-evidence/ocudu-steering-load-response-xay_k4f3/kpm.csv"
```

The validator creates a unique evidence directory, checks resolved Compose
configuration, runs the packaged acceptance and removes test containers.
Inputs are mounted read-only; the container has no network.
Input hashes and the packaged policy hash are checked against host files.
The validator does not build or automatically pull images.

## Retained acceptance evidence

Directory: ~/Work/oai-test-evidence/steering-common-compose-xiw18uth/

The formal Compose-validator run passed with no cleanup errors.
Both systems contributed 220 converted throughput rows. The policy hash
matched repository source:

06c9949f31a322de8d4f96976161105e683a32760445ae9be501a27db1794c5f

Evidence includes summary.json, result/summary.json, both common JSONL
outputs, image.json, resolved Compose configuration, stdout/stderr and
cleanup.log. Original CSV evidence remained unchanged.

Earlier direct Compose evidence: steering-common-metrics-60vsbvw7.

## Remaining work

Live dual-node recommendations remain pending. Cross-vendor PRB/capacity
normalization and actual migration execution are not claimed by this case.
