# Traffic steering policy: sequential OAI/OCUDU comparison

## Status and scope

Passed for separate single-UE OAI RFSim and OCUDU ZeroMQ runs on the
same Raspberry Pi and shared Open5GS core. OAI completed and cleaned up
before OCUDU started. Each side passed six UL/DL low-high-low phases.

This is a bounded functional comparison under the same offered UDP
loads, not a capacity ranking or equivalent-radio benchmark. No migration
recommendations or E2 control were performed.

## Prerequisites and images

Follow the [single-link prerequisites](README.steering-load-response.md).
Keep shared Open5GS and the baseline OCUDU RIC running. Experimental
RANs must be stopped. Required OAI laboratory/core addresses must be free.
The prepared OAI UE configuration must match its existing subscriber.

The validators use local images without building or automatically pulling.
The OAI validator pins the RIC, gNB, UE and collector images.
The OCUDU validator records its runtime image identities.

Pull the published OAI collector before testing:

```bash
sudo docker pull limx59/flexric-xapp:arm64-oai-steering-load-test@sha256:6074e3c22854de75f39efe613ff09db761d056e85a7204435e474e341cb96389
```

The remote collector digest and linux/arm64 manifest were verified.
The OAI collector uses the existing SDK base; original xApps and
third-party source trees were unchanged.

## Reproduce

From the repository root, run:

```bash
python3 -B test/ocudu/validate-steering-sequential-comparison.py
```

The wrapper runs these validators serially, stopping on failure:

1. `validate-oai-steering-load.py`
2. `validate-steering-load-response.py`

Each side offers 200 kbit/s, 1 Mbit/s and 200 kbit/s for ten seconds
per phase, first uplink and then downlink, with three-second pauses.
Each collector records for 110 seconds.

The OAI collector uses `deploy/ocudu/compose.oai-steering-load.yaml`;
its validator manages a unique OAI RAN Compose project.
The OCUDU side uses its existing dedicated single-link Compose service.

## Checks and measurement interpretation

Each side requires at least five interior reports per phase, receiver
rates within 80 to 120 percent of offered load and receiver loss at most
5 percent. Median KPM/receiver throughput ratios must be 0.70 to 1.50.
High-phase throughput must exceed both low phases by at least threefold;
final/initial low-phase throughput must remain within 0.70 to 1.30.

The wrapper independently reviews both retained CSV files and verifies
phase loads, chronological order and baseline RIC identity continuity.

OAI throughput uses RLC PDU byte-counter deltas divided by configured
granularity, in kbps. OCUDU uses provider mean RLC throughput in kbps.
OAI samples are associated by interior receipt timestamps; OCUDU uses
interior nominal KPM windows. These do not establish identical source
windows or identical protocol-layer accounting.

PRB percentages retain their implementation-specific semantics.
OAI and OCUDU PRB values must not be treated as interchangeable normalized
cell loads without further mapping. No capacity or congestion ranking follows.

## Retained acceptance evidence

Wrapper directory: `~/Work/oai-test-evidence/steering-sequential-comparison-4vgjwya0/`.

- oai: `oai-steering-load-h898l24_`
- ocudu: `ocudu-steering-load-response-xay_k4f3`

The wrapper retained child stdout/stderr, `comparison.csv` and
`summary.json`. Each child retained its own traffic, CSV and probe evidence.

| Phase | OAI receiver kbit/s | OCUDU receiver kbit/s | OAI KPM/iperf | OCUDU KPM/iperf | OAI PRB % | OCUDU PRB % |
| --- | --- | --- | --- | --- | --- | --- |
| uplink-low-before | 179.909 | 198.760 | 1.1051 | 1.0471 | 72.5 | 0.0 |
| uplink-high | 952.373 | 994.167 | 1.1478 | 1.0352 | 74.0 | 9.0 |
| uplink-low-after | 191.120 | 200.186 | 1.0384 | 1.0398 | 61.0 | 0.0 |
| downlink-low-before | 200.621 | 200.621 | 1.0918 | 1.0375 | 0.0 | 3.0 |
| downlink-high | 1003.214 | 1000.250 | 1.0440 | 1.0277 | 1.0 | 29.0 |
| downlink-low-after | 198.486 | 200.626 | 1.0957 | 1.0341 | 0.0 | 1.0 |

## Cleanup and remaining policy work

OAI test containers were removed before the OCUDU run. OCUDU cleanup
restored its original RAN configuration, stopped. The shared baseline
RIC identity remained unchanged across both runs; shared core services
were retained.

Dual-node recommendations and common metrics/cooldown rules remain
separate traffic-steering-policy work.
