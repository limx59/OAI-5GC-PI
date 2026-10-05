# Local ARM64 source build

Run from the repository root (the context is `open5gs`, not `base`):

```sh
sudo docker build --platform linux/arm64 --progress=plain \
  -f open5gs/docker_open5gs/base/Dockerfile.local \
  -t docker_open5gs:local-arm64 open5gs
```

## Validation on the ARM64 host

The image build completed successfully: all 3,932 native build targets compiled,
installation succeeded, and `npm ci` installed 813 packages. Image inspection
reported `linux/arm64`, working directory `/open5gs`, and command
`/open5gs_init.sh`. All 17 installed daemons returned version 2.7.2 with `-v`,
and their dynamic libraries resolved with the init script's library path.
Node was 20.20.2 and npm 10.8.2. Python click, mongo, ip and iptables were present.
`npm ls --depth=0` passed, and `next({dev: true}).prepare()` compiled successfully
in a network-disabled container without starting the HTTP listener or MongoDB.
The legacy react-jsonschema-form npm engine warning did not prevent installation.

During the first verification attempt, `--version` was mistakenly used instead
of `-v`; Open5GS 2.7.2 did not exit and AMF briefly initialized inside the
network-disabled container. That container was immediately stopped and removed.
No host directory was mounted, no ports were published, and no manual host
network changes were made. Subsequent version checks used the supported `-v`
option, which exits before initialization. No core-network integration tests
were run.

The original Dockerfile and deployment files are unchanged. The dedicated tag
does not replace the `docker_open5gs:latest` image used by existing deployments.
This command only builds an image; it does not start the core network.

`Dockerfile.local.dockerignore` overrides the context's global `.dockerignore`
for this Dockerfile. It allows source directories, Meson inputs, WebUI files
(including both npm manifests), subproject wraps, and the existing init script.
Host build/install directories, node_modules, logs, deployment YAML, environment
files, and private keys are excluded. The explicitly listed upstream TLS/HNET
example fixtures are retained because Meson requires them, along with `.yaml.in`
configuration templates. Do not replace these example fixtures with production
credentials; provide deployment credentials at runtime instead.

The main project comes from local source (2.7.2), with a fresh `/open5gs/build-local`
directory and a `/open5gs/install` prefix. Compilation and installation both use
`ninja -j 2`. Meson may download the dependencies specified by `subprojects/*.wrap`;
apt, base images, and npm also require network access. This is not an offline or
fully pinned build.

Ubuntu Focal matches the existing base image and provides the legacy `mongo`
client expected by `hss_init.sh`. Native ARM64 Node 20 and npm are copied from the
official Node image. WebUI dependencies are installed using the checked-in lock
file with `npm ci`; its package version is 2.7.0 even though the C project is
2.7.2. `/open5gs/webui` and the complete dependency tree are kept for the existing
`webui_init.sh` (`npm run dev`); no production WebUI build is required by that
script. The init script remains at `/open5gs_init.sh`, with `/open5gs` as the
working directory and libraries under `install/lib/aarch64-linux-gnu`.

For inspection without starting components, override the command and disable
networking, for example:

```sh
sudo docker image inspect docker_open5gs:local-arm64
sudo docker run --rm --network none --entrypoint /bin/bash \
  docker_open5gs:local-arm64 -ec '
    test -x /open5gs_init.sh
    /open5gs/install/bin/open5gs-amfd -v
    node --version
    npm --version
    python3 -c "import click"
  '
```
