# OAI RFSim gNB independent-container deployment

This deployment runs the OAI gNB with its embedded E2 agent, Near-RT RIC,
and each invoked Python xApp in separate containers. It connects the gNB
to the existing Open5GS AMF.

Run commands from the project root.

## Images and build settings

| Component | Image | Dockerfile |
| --- | --- | --- |
| OAI RFSim gNB | limx59/oai-gnb:arm64 | docker/oai/Dockerfile |
| Near-RT RIC | limx59/flexric-ric:arm64 | docker/flexric/Dockerfile |
| Python xApps | limx59/flexric-xapp:arm64 | docker/flexric/Dockerfile |

Compose definition: deploy/oai-flexric/compose.oai.yaml.

Both image and build settings are retained. Developers can pull published
images or build the checked-out source locally. Local builds do not push
images to Docker Hub.

The gNB uses E2AP V2 and KPM V3.00. Its KPM plugin is built from the same
embedded FlexRIC source as the gNB. Only KPM is exposed by this deployment.

This image supports RF simulation. UHD and physical-radio operation are
not included or validated.

## Prerequisites and network

Validated on an ARM64 Raspberry Pi. The host kernel must support SCTP.

| Component or setting | Address |
| --- | --- |
| External lab network | oai-pi-flexric-lab, 172.29.0.0/24 |
| RIC | 172.29.0.10 |
| gNB E2 network | 172.29.0.30 |
| External core network | docker_open5gs_default, 172.22.0.0/24 |
| gNB N2/N3 | 172.22.0.150 |
| Existing Open5GS AMF | 172.22.0.10 |

Check for subnet conflicts and confirm that 172.22.0.150 is available.
The existing core must match PLMN 001/01, TAC 1 and SST 1 without SD.

If the lab network does not exist, create it once:

```bash
sudo docker network create --driver bridge \
  --subnet 172.29.0.0/24 oai-pi-flexric-lab
```

The emulator deployment uses the same RIC address. Stop that deployment
before starting this one.

Configuration files under config/oai are mounted read-only. The gNB
receives IPC_LOCK and SYS_NICE capabilities, unlimited memlock and an
rtprio limit of 99. No host ports are published.

## Deploy published images

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile tools pull ric gnb xapp-nodes
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  up -d --no-build --force-recreate ric gnb
```

Inspect startup logs before running xApps. depends_on controls startup
order; it does not establish protocol readiness.

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --tail 100 ric gnb
```

## Build from source

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile tools build ric gnb xapp-nodes
```

The gNB build uses two jobs by default. Its initial compilation took
approximately 29 minutes on the validated Raspberry Pi.

## Verify node discovery and KPM lifecycle

Run each command after E2 Setup completes:

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile tools run --rm --no-deps xapp-nodes
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  --profile tools run --rm --no-deps xapp-kpm
```

Expected node: gNB 3584, PLMN 001/01.
The KPM xApp subscribes to DRB.UEThpDl and DRB.UEThpUl, then deletes
its subscription.

## Validation and limits

Validated with both the locally built image and a deployment recreated
after pulling Docker Hub images:

- Open5GS NG Setup completed during the local-image test.
- OAI E2 registration and independent xApp node discovery succeeded.
- KPM subscription and subscription deletion succeeded.
- The local-image gNB parsed S-NSSAI as SST 1 without SD.
- The initial tests had no attached UE. Subsequent RFSim UE registration,
  user-plane traffic and UE KPM reports are documented in
  [README.e2e.md](README.e2e.md).

Existing UERANSIM and ReDroid sessions do not demonstrate UE attachment
to this OAI RFSim gNB. The separate OAI UE workflow is documented in
[README.e2e.md](README.e2e.md). Physical-radio operation remains unvalidated.

RC interoperability remains unresolved. Emulator control acknowledgements
do not establish OAI handover or slice-control compatibility.

Published gNB image digest:

sha256:e2597cb10dab96eed3b54aa6816de53594b8fa6f38c33c7fe7dfaabf63c38041

The arm64 tag is mutable. Pull explicitly when deploying an updated image.

## Publish an updated gNB image

After building and validating the updated image:

```bash
sudo docker push limx59/oai-gnb:arm64
```

## Save logs and stop

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml \
  logs --no-color ric gnb > /tmp/oai-pi-oai-container-validation.log
```

```bash
sudo docker compose -f deploy/oai-flexric/compose.oai.yaml down
```

The external networks and existing Open5GS containers remain available.

For native execution without containers, see ../../test/oai/README.md.
For emulator container tests, see README.md.
