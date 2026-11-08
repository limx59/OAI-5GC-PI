# Open5GS UDR NF instance endpoint port

## Failure and fix

During UE registration, packet capture showed SCP attempting a TCP
connection to the UDR on port 80. The UDR listener and the `nudr-dr`
service endpoint advertised by NRF were both on port 7777.

The [UDR endpoint port patch](patches/patch-udr-nf-instance-endpoint-port.py)
allows the IPv4 UDR instance client to use an explicitly advertised
service port when matching endpoints for the instance address and
scheme agree. Missing, zero, or conflicting ports retain the existing
fallback behavior.

## ARM64 images

| Image | Purpose |
| --- | --- |
| `limx59/open5gs-sbi:arm64-udr-instance-port-fix` | Candidate SBI library with the UDR instance endpoint port fix. |
| `limx59/open5gs-udm:arm64-nudr-apiroot-trace` | Diagnostic UDM image that logs the `nudr-dr` target API root when selected through the instrumented path. |

Both published images were pulled as `linux/arm64`, and their image IDs
matched the corresponding local builds.

## Validation results

- With the candidate SCP running on the existing Open5GS test network,
  the UDR listener and its NRF advertisement changed from port 7777 to
  7771. The same SCP process associated the UDR instance client with
  each advertised port in turn.
- A separate double-worker OCUDU ZMQ run used the candidate UDM with
  the original SCP. UE registration, session establishment, and UPF
  probes passed. This run validated the candidate UDM configuration.
- The original Open5GS containers were restored after the experiments.
  The published images are available for separate validation or diagnosis.

The [OCUDU MAC cell executor regression](../ocudu/README.mac-cell-executor-fix.md)
covers the separate single-worker failure that occurred during initial
synchronization, before NAS registration.
