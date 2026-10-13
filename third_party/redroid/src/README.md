# Build ReDroid Android 12 for ARM64

## Overview

AOSP (Android Open Source Project) provides the Android operating system.
ReDroid adapts Android to run inside Linux containers.

This directory contains vendored ReDroid source snapshots, patches,
manifests, and upstream documentation. Full AOSP sources and external
prebuilt dependencies must be downloaded separately on the build host.

Build the ARM64 image on an x86-64 Linux machine, then transfer it to
the Raspberry Pi.

The official ARM64 image has been tested on our Raspberry Pi.
A complete build using these source snapshots has not yet been validated.

## Build configuration

| Parameter | Value |
| --- | --- |
| Build host | x86-64 Linux |
| Builder base | Ubuntu 20.04 |
| AOSP tag | android-12.0.0_r34 |
| Lunch target | redroid_arm64_only-userdebug |
| Image platform | linux/arm64 |
| Local image tag | redroid:12.0.0-local-arm64 |
| Pi memory page size | 4096 bytes |
| Rendering | Software, guest mode |
| Display | 720 x 1280 |
| Google apps | Not included |

Upstream documents approximately 200 GB of free disk space for the build.
We recommend at least 250 GB free SSD space and 32 GB RAM as a starting
point, with build parallelism adjusted to available resources.
These recommendations are not validated minimum requirements.

The upstream builder uses x86 host tools and multilib packages.
This procedure does not support native compilation on the Raspberry Pi.

## Source layout

| Stored directory | Destination in the AOSP tree |
| --- | --- |
| device_redroid | device/redroid |
| redroid-c2 | hardware/redroid/c2 |
| redroid-omx | hardware/redroid/omx |
| vendor_redroid | vendor/redroid |
| chromium-webview-stub | external/chromium-webview |
| redroid-patches | Patches for AOSP projects |
| local_manifests | Original upstream manifests |
| redroid-doc | Upstream documentation and builder Dockerfile |

- sources.lock.json records source URLs and snapshot commits.
- dependencies.lock.json records external prebuilt repository commits.
- local-manifest.locked.xml pins those external dependencies.
- prepare-source.py copies vendored sources and applies AOSP patches.

Original upstream license notices are preserved.
The generated manifest omits ReDroid projects supplied by our snapshots.
Do not install the original manifests alongside the generated manifest.

AOSP, external prebuilts, Git LFS objects, and build-tool dependencies
are still required. This is not a fully offline build.

## 1. Prepare the x86-64 build host

Install Docker Engine using your distribution's supported procedure.
Run the build as a regular non-root user with Docker access.

On an Ubuntu host:

```bash
sudo apt-get update
sudo apt-get install -y git git-lfs curl python3 rsync
git lfs install
docker version
uname -m
```

The host architecture must report x86_64.

Install Google's repo launcher:

```bash
mkdir -p "$HOME/.local/bin"
curl -fL https://storage.googleapis.com/git-repo-downloads/repo \
  -o "$HOME/.local/bin/repo"
chmod +x "$HOME/.local/bin/repo"
export PATH="$HOME/.local/bin:$PATH"
repo version
```

If no Git identity is configured, set your own name and email:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## 2. Set up the source workspace

Run on the x86-64 build host:

```bash
mkdir -p "$HOME/Work"
git clone --branch feature/redroid-integration \
  https://gitlab.com/limx59/oai-5gc-pi.git "$HOME/Work/oai-5gc-pi"

export PROJECT_ROOT="$HOME/Work/oai-5gc-pi"
export REDROID_SOURCE="$PROJECT_ROOT/third_party/redroid/src"
export AOSP_DIR="$HOME/Work/redroid-aosp-12"
```

If the project is already cloned, use its existing location instead.
These instructions require the commit containing this src directory.

Keep the full AOSP workspace outside the OAI-Pi Git repository.
Use a fresh AOSP directory for the following synchronization steps.

## 3. Synchronize AOSP and external dependencies

Run on the x86-64 build host:

```bash
mkdir -p "$AOSP_DIR"
cd "$AOSP_DIR"
repo init -u https://android.googlesource.com/platform/manifest \
  --git-lfs -b android-12.0.0_r34

mkdir -p .repo/local_manifests
cp "$REDROID_SOURCE/local-manifest.locked.xml" \
  .repo/local_manifests/oai-pi-redroid.xml

repo sync -c -j4 --fail-fast
```

Do not add the original upstream local manifests alongside this file.

Inspect the downloaded WebView APKs:

```bash
find "$AOSP_DIR/external/chromium-webview" \
  -type f -name '*.apk' -exec du -h {} +
```

Small text files containing Git LFS pointers are not usable APKs.
Resolve failed LFS downloads before building.

Save the resolved revisions of repo-managed projects:

```bash
cd "$AOSP_DIR"
repo manifest -r -o "$AOSP_DIR/resolved-manifest.xml"
```

Vendored ReDroid revisions are recorded separately in sources.lock.json.

## 4. Overlay sources and apply patches

Run on the build host after synchronization completes:

```bash
python3 "$REDROID_SOURCE/prepare-source.py" overlay "$AOSP_DIR"
python3 "$REDROID_SOURCE/prepare-source.py" patch "$AOSP_DIR"
```

The overlay preserves downloaded WebView prebuilt directories.
Apply patches once to a freshly synchronized, unpatched AOSP tree.

The patch helper checks target repositories and stops on failure.
If a patch fails, inspect the affected repository with git status.
Resolve the conflict and use git am --continue, or abandon that project's
incomplete operation with git am --abort.

Earlier projects may already have patches applied. Do not blindly rerun
the helper over a partially patched tree. Restore a known clean workspace
or deliberately complete the remaining patches.

## 5. Build the ARM64 Android system

On the x86-64 host, use a regular user whose UID and GID are not zero:

```bash
docker build --platform linux/amd64 \
  --build-arg userid="$(id -u)" \
  --build-arg groupid="$(id -g)" \
  --build-arg username="$(id -un)" \
  -t oai-pi-redroid-builder:android12 \
  "$REDROID_SOURCE/redroid-doc/android-builder-docker"
```

The upstream Dockerfile is retained unchanged. Its apt and pip dependencies
are not fully pinned and may require future maintenance.

Start the builder:

```bash
docker run -it --rm --privileged \
  --hostname redroid-builder \
  -v "$AOSP_DIR:/src" \
  oai-pi-redroid-builder:android12
```

Inside the builder container:

```bash
cd /src
source build/envsetup.sh
lunch redroid_arm64_only-userdebug
m -j4
exit
```

Adjust parallelism to available memory and CPU resources.
Expected output directory:

```text
out/target/product/redroid_arm64_only/
```

Packaging requires system.img and vendor.img from this directory.

## 6. Package the Docker image

Run on the x86-64 build host after compilation succeeds.
Use temporary mount points to preserve the build output directories.
Run the following block as one complete command:

```bash
(
set -euo pipefail
product="$AOSP_DIR/out/target/product/redroid_arm64_only"
test -f "$product/system.img"
test -f "$product/vendor.img"
mount_root="$(mktemp -d)"
mkdir "$mount_root/system" "$mount_root/vendor"

cleanup() {
  local failed=0
  for directory in vendor system; do
    if mountpoint -q "$mount_root/$directory"; then
      sudo umount "$mount_root/$directory" || failed=1
    fi
  done
  if [ "$failed" -eq 0 ]; then
    rmdir "$mount_root/vendor" "$mount_root/system" "$mount_root"
  else
    echo "Unmount failed; retained mount points: $mount_root" >&2
  fi
}
trap cleanup EXIT

sudo mount -o loop,ro "$product/system.img" "$mount_root/system"
sudo mount -o loop,ro "$product/vendor.img" "$mount_root/vendor"

sudo tar --xattrs -c -C "$mount_root" vendor \
  -C "$mount_root/system" --exclude='./vendor' . |
  docker import --platform=linux/arm64 \
    -c 'ENTRYPOINT ["/init","qemu=1","androidboot.hardware=redroid"]' \
    - redroid:12.0.0-local-arm64
)
```

Inspect the generated image:

```bash
docker image inspect redroid:12.0.0-local-arm64 \
  --format 'Architecture={{.Architecture}} Entrypoint={{json .Config.Entrypoint}}'
```

Expected architecture: arm64.
Image metadata inspection does not prove that Android boots successfully.
Runtime validation must be performed on the Raspberry Pi.

## 7. Transfer the image to Raspberry Pi

On the x86-64 build host:

```bash
docker save -o "$HOME/redroid-12-arm64.tar" redroid:12.0.0-local-arm64
sha256sum "$HOME/redroid-12-arm64.tar"
scp "$HOME/redroid-12-arm64.tar" limx59@10.0.0.190:~/
```

Replace the SSH username and IP address for your environment.

On the Raspberry Pi:

```bash
sha256sum "$HOME/redroid-12-arm64.tar"
sudo docker load -i "$HOME/redroid-12-arm64.tar"
sudo docker image inspect redroid:12.0.0-local-arm64 \
  --format 'Architecture={{.Architecture}}'
```

Compare the archive checksums on both machines.
The imported image architecture must be arm64.

Use docker load for a docker save archive.
Do not use docker import for this archive.
Keep large image archives and build outputs outside the Git repository.

## 8. Configure the Raspberry Pi deployment

Follow ../README.md for the 4 KB kernel and Binder requirements.
Run from the OAI-Pi project root on the Raspberry Pi:

```bash
sudo third_party/redroid/prepare-host.sh
sudo docker volume create redroid_data
```

Create an override to select the source-built image:

```bash
cat > third_party/redroid/compose.source.override.yaml <<'YAML'
services:
  redroid:
    image: redroid:12.0.0-local-arm64
YAML
```

If an existing container is named redroid, preserve it before replacement:

```bash
sudo docker stop redroid
sudo docker rename redroid redroid-official-backup
```

The backup container name must be unused.
Back up important Android data before testing a different image.
Do not run two containers simultaneously against the same redroid_data volume.
A different image may modify that volume or be incompatible with its contents.

Validate and start the source-built image:

```bash
sudo docker compose \
  -f third_party/redroid/compose.yaml \
  -f third_party/redroid/compose.source.override.yaml config --quiet

sudo docker compose \
  -f third_party/redroid/compose.yaml \
  -f third_party/redroid/compose.source.override.yaml up -d --pull never

sudo docker exec redroid /system/bin/getprop sys.boot_completed
```

Wait for sys.boot_completed to return 1.

If Android does not boot, inspect the container state and logs:

```bash
sudo docker inspect redroid --format '{{json .State}}'
sudo docker logs --tail=100 redroid
sudo docker exec redroid /system/bin/logcat -d -t 200
```

The logcat command requires the container to be running.

## 9. Connect Android browser traffic to the UE data path

Verify that Open5GS and UERANSIM are running and the UE has a PDU session.
On the Raspberry Pi, from the project root:

```bash
sudo docker exec nr_ue apt-get update
sudo docker exec nr_ue apt-get install -y --no-install-recommends \
  tinyproxy curl ca-certificates

sudo third_party/redroid/connect-network.sh
sudo third_party/redroid/configure-proxy.sh
```

The packages installed in nr_ue are lost if that container is recreated.
Include them in a maintained UE image for a persistent deployment.

Test the proxy using the actual UE proxy address printed by the scripts:

```bash
sudo docker exec nr_ue curl -4 --noproxy '' \
  --proxy http://172.22.0.24:8888 \
  --connect-timeout 10 --max-time 20 -I https://www.google.com
```

Expect a successful CONNECT response followed by the website response.
Use the SSH tunnel, ADB, and scrcpy instructions in ../README.md to view
Android. Inspect Tinyproxy logs for requests from the ReDroid container.

Re-run the network and proxy scripts after container recreation or a
UE PDU-address change. They are not automatically restored by this recipe.

ReDroid does not perform cellular registration. UERANSIM performs that role.
Only applications honoring the Android HTTP proxy use this browser path.
UDP/QUIC traffic, DNS queries, and other applications are not guaranteed
to pass through the UE PDU session.

## 10. Roll back to the previous container

If the official-image container was preserved as redroid-official-backup,
run from the project root:

```bash
sudo docker compose \
  -f third_party/redroid/compose.yaml \
  -f third_party/redroid/compose.source.override.yaml down

sudo docker rename redroid-official-backup redroid
sudo docker start redroid
```

Do not use down -v. The external redroid_data volume is retained.

Container rollback does not undo changes to the shared Android data volume.
Restore a separate data backup if necessary.

After Android finishes booting, re-run connect-network.sh and
configure-proxy.sh to restore the UE browser path.

## Availability and reproducibility

Vendored source snapshots avoid downloading those specific ReDroid
repositories again. Builds still depend on AOSP hosting, external prebuilts,
Git LFS objects, base images, apt, pip, and the repo tool.

For independent long-term builds, maintain permitted mirrors of these
inputs and retain the resolved manifest, source revisions, verified image
archives, and checksums. Store large archives outside Git.

An existing local Docker image can run even if its upstream image is removed.
A source rebuild still requires all remaining inputs and successful
build and runtime validation.

Pinned dependency revisions make versions explicit; they do not guarantee
continued upstream availability or compatibility with Android 12.

## Upstream references

- https://github.com/remote-android/redroid-doc
- https://github.com/remote-android/local_manifests
- https://github.com/remote-android/redroid-patches
- https://source.android.com/docs/setup/download

A snapshot of the upstream build documentation is stored in redroid-doc/.
