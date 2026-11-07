# OCUDU ZeroMQ laboratory

See the [integration guide and TODO](../../test/ocudu/README.md) for validated scope, image builds, prerequisites, regression and cleanup.

The passed configuration combines `compose.zmq.yaml` and `compose.zmq-worker-test.yaml`. The passed workflow uses published, pull-verified ARM64 Docker Hub images.

## Bounded single-UE session stability

Use `compose.session-stability-runner.yaml` for the packaged test runner.
It manages the RAN through `compose.zmq.yaml` and
`compose.session-stability.yaml`, with its own image selection and
generated two-worker configuration.

The published ARM64 v2 runner passed the 24-hour single-UE ZMQ validation.
See [session stability: build, run, results and limitations](../../test/ocudu/README.session-stability.md).
