# ReDroid Android UI for the Open5GS / UERANSIM Lab

## Purpose

This directory contains deployment files for an Android UI backed by ReDroid.
UERANSIM provides the actual simulated 5G UE and gNB.

Android browser traffic uses an HTTP proxy inside the UERANSIM UE container.
Tinyproxy binds its outgoing connections to the UE's PDU-session IPv4 address.

Traffic path:

ReDroid browser → Tinyproxy → UE TUN → UERANSIM gNB → Open5GS UPF → Internet.

ReDroid does not perform 5G registration or provide a modem/RIL integration
with UERANSIM. The Android cellular indicators do not represent the simulated
UE's registration state. Applications that ignore the Android HTTP proxy,
UDP/QUIC traffic, and DNS queries are not guaranteed to use the UE data path.

## Files

| File | Purpose |
| --- | --- |
| `compose.yaml` | ReDroid container definition |
| `prepare-host.sh` | Check page size, load kernel modules, and prepare Binder |
| `connect-network.sh` | Attach the core network and configure Android routing |
| `configure-proxy.sh` | Detect the PDU address and configure Tinyproxy and Android |
| `README.md` | Installation, operation, validation, and troubleshooting |

Docker stores the Android image and the `redroid_data` named volume.
Do not add Android images, volume contents, or private credentials to Git.

## Validated Environment

- Raspberry Pi 5, approximately 8 GB RAM.
- Debian 12 / Raspberry Pi OS, ARM64.
- Docker Engine 29.8.2 and Docker Compose 5.6.0.
- Open5GS 2.7.2 and UERANSIM 3.2.6.
- ReDroid image: `redroid/redroid:12.0.0_64only-latest`.
- Software rendering, 720 × 1280 display.
- Host page size: 4096 bytes after switching to `kernel8.img`.

The image tag is mutable. The image index digest observed during testing was:

`sha256:a6c464bbedcf1dcb67dbf91f329fbb19bee5b50631f0ca6bda6ed7c41b0e64e2`

This Compose file retains the tested tag; it does not pin that digest.

## Prerequisites

Docker, Compose, host Python 3, and a working Open5GS / UERANSIM deployment
must already be available.

The core network must exist, and `nr_ue` must have a successful PDU session.
A running container alone does not prove that the UE process is healthy.

### Host Page Size

Check:

```bash
getconf PAGESIZE
uname -r
```

The tested Android 12 image exited with code 139 on the original 16 KB-page
kernel. It booted successfully after switching to a 4 KB-page kernel.

On the tested Raspberry Pi, these files were present:

- `/boot/firmware/kernel8.img`
- `/boot/firmware/initramfs8`
- `/lib/modules/6.12.109+rpt-rpi-v8`

Before changing the kernel, verify the corresponding files on your own system,
back up `/boot/firmware/config.txt`, and add the following under `[all]`:

```ini
kernel=kernel8.img
```

Reboot and confirm that `getconf PAGESIZE` returns `4096`.

The lab backup is `/boot/firmware/config.txt.before-redroid-4k`.
The preparation script does not modify boot configuration or reboot the host.

### Prepare the Host

From this directory:

```bash
sudo ./prepare-host.sh
```

This loads `md5`, `sctp`, `tun`, and the legacy IPv4/IPv6 NAT/filter modules.
It mounts Binder at `/dev/binderfs` and grants Android services access to
`binder`, `hwbinder`, and `vndbinder`.

These permissions match the tested privileged-container setup.
Use this configuration on a trusted development host.

Binder mounting, permissions, and module loading must be restored after reboot.
No boot-time service is installed by these files.

## ReDroid Installation

### Fresh Deployment

Use these steps only when no container named `redroid` already exists.

```bash
sudo docker pull --platform linux/arm64 redroid/redroid:12.0.0_64only-latest
sudo docker volume create redroid_data
sudo docker compose -f compose.yaml config --quiet
sudo docker compose -f compose.yaml up -d
sudo docker exec redroid /system/bin/getprop sys.boot_completed
```

Android is ready when the last command returns `1`. An empty result means
boot has not completed; inspect the container and retry after a short interval.

### Existing Manually Created Container

The currently validated lab container was created with `docker run`.
Saving `compose.yaml` does not transfer ownership to Compose.

Do not run `compose up` against the existing same-name container.
Continue to manage it with `docker start redroid` and `docker restart redroid`.
A future migration must stop and preserve or remove the old container before
Compose creates its replacement. Preserve the `redroid_data` volume and never
run two Android containers against that volume simultaneously.

## Configuration Parameters

| Parameter | Value |
| --- | --- |
| Container name | `redroid` |
| Platform | `linux/arm64` |
| Privileged mode | Enabled |
| Initial network | Docker `bridge` |
| Additional network | `docker_open5gs_default`, attached by script |
| ADB mapping | `127.0.0.1:5555:5555` |
| Android data | External named volume `redroid_data` |
| Shared memory | `androidboot.use_memfd=true` |
| Rendering | `androidboot.redroid_gpu_mode=guest` |
| Display | Width `720`, height `1280` |
| Restart policy | `no` |

The original `--memory=3g` setting was discarded by Docker because host memory
limit capabilities were unavailable. It is omitted from Compose; no 3 GB
memory cap is enforced by this deployment.

## UE Proxy Dependencies

Install these packages in the running UE container:

```bash
sudo docker exec nr_ue apt-get update
sudo docker exec nr_ue apt-get install -y --no-install-recommends tinyproxy curl ca-certificates
```

These packages remain after restarting the same container but are lost when
it is removed and recreated from the original UERANSIM image.
They are not yet included in a derived image.

## Connect Android to the UE Proxy

After Android boot and UE PDU-session establishment:

```bash
sudo ./connect-network.sh
sudo ./configure-proxy.sh
```

The scripts detect container addresses on the core network.
The proxy script reads the IPv4 address on `uesimtun0` and checks that traffic
from that source address routes through the TUN interface.

The network script installs this destination-specific Android policy rule:

```text
priority 9000 to <UE-container-IP>/32 lookup main
```

This lets Android reach the UE over its additional Docker interface without
replacing Android's default routing rules.

Tinyproxy listens on the UE container's core-network address, port `8888`,
and binds outgoing connections to the PDU-session address.
It allows localhost, the ReDroid core-network address, and the UE core-network
address for diagnostic requests. HTTPS CONNECT ports are `443` and `563`.
Port `8888` is not published on the host.

The original proxy configuration is backed up once at:

`/etc/tinyproxy/tinyproxy.conf.before-redroid`

The generated configuration replaces `/etc/tinyproxy/tinyproxy.conf`.
Android's global HTTP proxy is set to `<UE-container-IP>:8888`.

Optional script environment variables:

| Variable | Default |
| --- | --- |
| `REDROID_CONTAINER` | `redroid` |
| `UE_CONTAINER` | `nr_ue` |
| `CORE_NETWORK` | `docker_open5gs_default` |
| `UE_TUN_INTERFACE` | `uesimtun0`, proxy script only |

Example:

```bash
sudo env UE_CONTAINER=nr_ue ./configure-proxy.sh
```

Re-run the network script after Android restarts.
Re-run the proxy script after the UE PDU address changes or Tinyproxy stops.
Re-run both after container recreation.

## Validation Without a GUI

The tested addresses were:

- ReDroid core-network IP: `172.22.0.3`
- UE container IP: `172.22.0.24`
- UE PDU IP: `192.168.100.244`

These are observations, not fixed addresses required by the scripts.

Check Android's route:

```bash
sudo docker exec redroid /system/bin/ip -4 route get 172.22.0.24
```

The tested result selected `eth1`, source `172.22.0.3`.

Check the proxy:

```bash
sudo docker exec nr_ue curl -4 --noproxy '' --proxy http://172.22.0.24:8888 --connect-timeout 10 --max-time 20 -I https://www.google.com
```

The recorded result on 2026-10-05 was:

```text
HTTP/1.0 200 Connection established
HTTP/2 200
```

This validates the proxy's HTTPS path. It does not independently verify
Android browser rendering.

Check logs:

```bash
sudo docker exec nr_ue tail -n 40 /var/log/tinyproxy/tinyproxy.log
sudo docker logs --tail=80 nr_ue
sudo docker logs --tail=80 upf
```

For stronger path verification, capture traffic on the UE TUN and UPF, or
perform a controlled UPF outage test. Those tests are not included in the
recorded proxy validation.

## Android UI from macOS

Install tools on the Mac:

```bash
brew install --cask android-platform-tools
brew install scrcpy
```

Keep an SSH tunnel open in one terminal:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:5555:127.0.0.1:5555 limx59@10.0.0.190
```

Use your own Raspberry Pi address and SSH account.
No terminal output after successful authentication is normal.

In another Mac terminal:

```bash
adb connect 127.0.0.1:5555
scrcpy -s 127.0.0.1:5555
```

Open the tested browser from the Raspberry Pi:

```bash
sudo docker exec redroid /system/bin/am start -W -n org.chromium.webview_shell/.WebViewBrowserActivity -a android.intent.action.VIEW -d https://example.com
```

The tested browser component is the ReDroid image's WebView shell.
ADB is exposed only on the Raspberry Pi's loopback address.

## Reboot Recovery

1. Run `prepare-host.sh` before starting the lab containers.
2. Start MongoDB and verify `db.adminCommand({ping: 1})`.
3. Start NRF/SCP and the other core functions.
4. Verify AMF SCTP listening and SMF/UPF PFCP association.
5. Start gNB, verify NG Setup, then start UE and verify its PDU session.
6. Start ReDroid and wait for `sys.boot_completed=1`.
7. Run `connect-network.sh` and `configure-proxy.sh`.
8. Restore the Mac SSH tunnel and scrcpy when needed.

No automatic core startup or readiness orchestration is installed.
The WebUI, Prometheus, and Grafana containers require separate startup.

## Troubleshooting

| Symptom | Recorded cause or next check |
| --- | --- |
| ReDroid exits with code 139 | Check host page size; the tested image required 4 KB pages |
| Android never finishes booting | Check Binder mount and device permissions |
| SCTP socket creation fails | Load `sctp` |
| SCTP listen returns ENOSYS | Check dmesg; loading `md5` resolved the recorded failure |
| UPF reports TUN "No such device" | Load `tun`, then restart UPF |
| Legacy iptables tables unavailable | Load the NAT/filter modules used by `prepare-host.sh` |
| UE reports no associated UPF | Check UPF initialization and PFCP association |
| Android routes proxy traffic through eth0 | Re-run `connect-network.sh` |
| Proxy returns HTTP 403 | Check the client source IP against Tinyproxy Allow entries |
| curl returns error 77 | Install `ca-certificates` in the UE container |
| Browser breaks after UE reconnect | Re-run `configure-proxy.sh` with the new PDU address |
| ADB connection refused | Check ReDroid and keep the SSH tunnel open |
| Container is Up but UE/gNB is not working | Inspect daemon logs; the original entrypoint keeps a shell alive |

## Persistence and Current Limits

- Android `/data` persists in `redroid_data`.
- Image downloads persist in Docker storage.
- Binder setup and kernel modules are not configured for automatic boot recovery.
- Android policy routing is runtime configuration.
- Tinyproxy requires manual startup/configuration after UE-container restart.
- UE proxy packages/configuration are not preserved across container recreation.
- Dynamic addresses must be detected again after network or PDU changes.
- IPv4 browsing was validated; end-to-end IPv6 browsing was not validated.
- The ReDroid container remains privileged and has no enforced memory limit.
- This integration is a development lab configuration.
