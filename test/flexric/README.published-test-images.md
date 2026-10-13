# Additional published ARM64 test images

Published and pull-verified on 2026-10-12, Pacific time.
Architecture, original image identity and push digest were verified.
Publication verification does not extend the functional validation scope
of historical test builds. Use the corresponding experiment guide.
Original local tags and existing deployment defaults are retained unless
explicitly updated by the relevant workflow.

| Docker Hub image | Image-index digest |
| --- | --- |
| `limx59/oai-pi-flexric-emulator:arm64-local-arm64-test` | `sha256:c765e7bcb375916d6671429f23040295ddece886accad07f3f0f9c69e925687f` |
| `limx59/oai-pi-flexric-xapp:arm64-multi-agent-test` | `sha256:aec1fb4b061a53a11a653df0b622b0167135e6195cdaccb831a9dfe215779bd3` |
| `limx59/oai-pi-flexric-xapp:arm64-oai-mac-counters-test` | `sha256:9a0e466ae72cbc90cd38bf4be0296d7be7d5ea6ce6324bda3ddb876d8b649de0` |
| `limx59/oai-pi-flexric-xapp:arm64-qos-multi-agent-test` | `sha256:413acdbecc5c6cf04b878d1f3ac9de4cf1dd9a8a7bc1a4e5433228b0dc808bbf` |
| `limx59/oai-pi-flexric-xapp:arm64-slice-multi-agent-test` | `sha256:b367777ec5193533c2428f39ab8582faaff5da1cd0f52af528141b259e326b7b` |
| `limx59/oai-pi-flexric-xapp:arm64-subscription-cleanup-regression-test` | `sha256:84be0994893389707197b13b560bf883d4c6a2f9a8915528b28f5bc7b4b056fb` |
| `limx59/oai-pi-flexric-xapp:arm64-subscription-cleanup-test` | `sha256:cc82b9a45449d07c6b3ff11d527d4555f4f02375f8a6fb0d28d7128ad98accb6` |
| `limx59/oai-pi-oai-prb-bench:arm64-nr-prb-baseline-test` | `sha256:e787f62aa577ce8bf58dbb3813458c5a13d8940185e1c541aca1e64934696060` |
| `limx59/oai-pi-oai-prb-bench:arm64-nr-prb-quota-test` | `sha256:0a503d4d1a8a6f96a8c4a495c096ee0fcf184ad3b3538457b1beb84dfa27a84e` |
| `limx59/oai-pi-oai-prb-bench:arm64-nr-prb-trace-test` | `sha256:8ed25f60099932b45f61dd257febdc768cb26d04753a8eb52c7cd8af1a983edd` |

The separately published dual-cell 100 ms collector is
`limx59/oai-pi-flexric-xapp:arm64-oai-mac-100ms-test`, with digest
`sha256:00b7700a6fa6184033e73188240d138b61f5a678aa0e0f8a35e09294fbd5fea1`.

The dual-cell validator and regression wrapper default to this collector.
The PRB Agent Dockerfile uses the published quota benchmark as its base.
See [dual-cell validation](README.oai-multi-cell.md) and
[PRB execution](README.prb-execution.md) for deployment and test scope.
