# FlexRIC independent-container lab

This deployment runs the Near-RT RIC, gNB emulator, and each invoked xApp
in separate containers on a dedicated Docker bridge network.

## Images and source

| Component | Docker Hub image | Dockerfile target |
| --- | --- | --- |
| Near-RT RIC | limx59/flexric-ric:arm64 | ric |
| gNB emulator | limx59/flexric-emulator:arm64 | emulator |
| Python xApps and native handover demo | limx59/flexric-xapp:arm64 | xapp |

Build definition: docker/flexric/Dockerfile.
Build-context exclusions: docker/flexric/Dockerfile.dockerignore.
Deployment definition: deploy/oai-flexric/compose.emulator.yaml.

The Compose file retains both image and build settings:
- Pull uses the published Docker Hub images.
- Build compiles the checked-out source and tags the images with those names.
- Building locally does not push to Docker Hub.

Validated on an ARM64 Raspberry Pi with Docker and Docker Compose.
The host kernel must support SCTP. The arm64 tag is mutable; pull it
explicitly when deploying an updated image.

## Network and configuration

| Setting | Value |
| --- | --- |
| External Docker network | oai-pi-flexric-lab |
| Subnet | 172.29.0.0/24 |
| RIC address | 172.29.0.10 |
| Emulator address | 172.29.0.20 |
| E2 SCTP port | 36421 |
| E42 SCTP port | 36422 |

Check for subnet conflicts before creating the network.
Create it once:

```bash
sudo docker network create --driver bridge \
  --subnet 172.29.0.0/24 oai-pi-flexric-lab
```

The three configuration files under config/emulator are mounted read-only.
All point to RIC address 172.29.0.10.
The xApp database is disabled.

No host ports are published. The lab uses its own network and does not
require changing the existing Open5GS or UERANSIM containers.

## Deploy from Docker Hub

Run the following commands separately from the project root.

Validate Compose:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  --profile tools config --quiet
```

Pull all three image types:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  --profile tools pull ric emulator xapp-nodes
```

Create or recreate RIC and emulator containers without building:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  up -d --no-build --force-recreate ric emulator
```

Check startup:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  logs --tail 30 ric emulator
```

Wait for the emulator's E2 SETUP RESPONSE rx before invoking an xApp.
depends_on sets startup order; it does not establish E2 readiness.

## Run independent xApp containers

The tools profile keeps these finite demos out of the default background
services. Each run creates a separate container and removes it on exit.

Node discovery:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  --profile tools run --rm --no-deps xapp-nodes
```

KPM reporting:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  --profile tools run --rm --no-deps xapp-kpm
```

Synthetic steering recommendation to one emulator control request:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  --profile tools run --rm --no-deps xapp-steering
```

The steering service explicitly selects the installed native binary:
 /usr/local/bin/flexric/xApp/c/xapp_handover_control.
It uses synthetic UE 1, source CGI 256, and target CGI 512.
The emulator acknowledges the request without performing actual handover.

## Build locally from source

On an ARM64 development host, build all three image types:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  --profile tools build ric emulator xapp-nodes
```

The shared builder compiles FlexRIC in Debug mode with E2AP V2,
KPM V3.00, Python SDK support, and the project handover demo.
Unit-test build targets are disabled in this runtime image build.
The native emulator regression suite is documented in test/xapp/README.md.

The runtime includes libpython3.11 for the native Python SDK.
RIC and emulator use line-buffered output and SIGINT as their stop signal.

## Publish locally built images

Authenticate to Docker Hub locally if required. Do not put credentials
in the Compose file or repository. Push each image separately:

```bash
sudo docker push limx59/flexric-ric:arm64
```

```bash
sudo docker push limx59/flexric-emulator:arm64
```

```bash
sudo docker push limx59/flexric-xapp:arm64
```

Pulling after a local build replaces the local tag with the published
registry version. Push intended updates before pulling that tag again.

## Logs and cleanup

Save RIC and emulator logs before removing the containers:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml \
  logs --no-color ric emulator > /tmp/oai-pi-flexric-lab.log
```

Stop and remove the Compose containers:

```bash
sudo docker compose -f deploy/oai-flexric/compose.emulator.yaml down
```

The external network and images remain available.
Do not commit generated runtime logs.

## Validation

Validated on Raspberry Pi:
- All three image targets built successfully.
- Python SDK imported successfully in the runtime container.
- Separate RIC and emulator containers completed E2 setup.
- A separate node-listing container discovered lab node 1, PLMN 505/1.
- A separate KPM container received DL and UL measurements and completed
  subscription deletion.
- Steering control received an xApp ACK; the emulator logged UE 1,
  target CGI 512, and CONTROL ACKNOWLEDGE tx.
- Compose configuration and source builds succeeded with registry image names.
- All three images were pushed to Docker Hub and pulled through Compose.
- Containers recreated from the pulled images completed E2 setup,
  KPM reporting/deletion, and steering control acknowledgment.

Published image-index digests for this validated upload:

| Image | Digest |
| --- | --- |
| limx59/flexric-ric:arm64 | sha256:c319a545ecdf024aca6360f93704bf3751f38894fbfb2dd851de48eee9d1225b |
| limx59/flexric-emulator:arm64 | sha256:c765e7bcb375916d6671429f23040295ddece886accad07f3f0f9c69e925687f |
| limx59/flexric-xapp:arm64 | sha256:8787c338c3960278e02d4a55dd7a8cec9c402c33e1edc12b54989b61e54b0914 |

These tests validate emulator reporting and control communication.
They do not validate actual handover, scheduler enforcement, or energy savings.
OAI gNB container construction and interoperability are a separate next step;
the native OAI KPM test is documented in test/oai/README.md.
