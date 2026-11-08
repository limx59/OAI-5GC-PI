# OCUDU integrated workflow regression

The Python entry point runs six validators in sequence on Raspberry Pi
ARM64 with one OAI UE connected to an OCUDU gNB over ZeroMQ. It checks
baseline container continuity after each stage.

## Run the regression

Use the existing Open5GS test network, private ZMQ UE configuration,
running baseline FlexRIC RIC and local ARM64 test images. Stop the
experimental gNB and UE before starting. Run from the repository root.

    sudo -v
    python3 -B test/ocudu/validate-integrated-workflow.py --check-only
    python3 -B test/ocudu/validate-integrated-workflow.py

## Validation results

| Stage | Observed result |
| --- | --- |
| Testmode state | Seven Compose configuration cases passed. |
| MAC cell executor | Both worker counts established the UE tunnel and passed two UPF probes each. |
| KPM full chain | 40 reports, 80 CSV rows, independent F1 identity match and zero UDP packet loss in both directions. |
| xApp disconnection | FlexRIC cleared the subscription after abrupt xApp exit. A subsequent subscription and traffic checks passed. |
| Subscription rejection | The same xApp recovered, received reports and deleted its valid subscription. |
| Delete rejection | Reports continued after rejection. The retry succeeded and the observation window showed no late reports. |

All six stages passed. The experimental RAN was restored to its original
configuration in the stopped state. The workflow summary is retained
outside Git.

    ~/Work/oai-test-evidence/ocudu-integrated-workflow-lmbsaw6l/summary.json

The workflow covers bounded single-UE software-radio scenarios.
