# Local OAI and FlexRIC Build Scripts

These scripts use existing local source trees. They do not clone sources
or start network services. Run them as a regular user.

## Source revisions

| Project | Local directory | Branch | Commit |
| --- | --- | --- | --- |
| OAI RAN | oai | develop | f8f769592a7030be88ede4bb5ca66fa1ca6a80e0 |
| FlexRIC | flexric | br-flexric | 736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8 |

The source directories currently retain their own upstream Git repositories.
They are not automatically included when committing these scripts.

## Validation status

Validated on Raspberry Pi 5, ARM64, Debian Bookworm:

- UHD 4.8.0.0 with the OAI TDD patch: built and installed successfully.
- OAI gNB with USRP and E2 support: all 12,673 build tasks completed.
- nr-softmodem: direct dynamic library dependencies resolved.
- Standalone FlexRIC: built and installed, including the Python xApp SDK.
- nearRT-RIC: direct dynamic library dependencies resolved.
- RIC startup: eight service models loaded and E2/E42 initialized.
- The 10-second startup check ended with the requested SIGINT.

Executable-stack linker warnings occurred during OAI and FlexRIC builds.
NR UE compilation, CU/DU deployment, hardware operation, and OAI/FlexRIC
E2 interoperability have not yet been validated.

The OAI dependency helper explicitly includes Debian 12 support.

## Script behavior

- build-oai.sh: install dependencies or build the gNB / NR UE.
- build-flexric.sh: install dependencies, build, or install FlexRIC.
- Build parallelism defaults to two jobs.
- Commands stop on failure; existing build outputs are not automatically deleted.
- Dependency installation and FlexRIC installation use sudo.
- OAI binaries remain in the upstream build tree.
- NR UE is a simulated terminal target, not an O-RU target.

## OAI RAN

Run from the project root. Dependency installation modifies the host:

```bash
# Build and install local UHD first; see the UHD section below.
OAI_HARDWARE=None ./scripts/build-oai.sh deps
./scripts/build-oai.sh gnb
# Optional; NR UE compilation has not yet been validated.
./scripts/build-oai.sh nrue
```

Run each command separately and inspect its result before continuing.

| Variable | Default | Purpose |
| --- | --- | --- |
| OAI_SOURCE | PROJECT_ROOT/oai | Local OAI source directory |
| BUILD_JOBS | 2 | Maximum build parallelism |
| OAI_HARDWARE | USRP | RF backend passed to build_oai |
| OAI_BUILD_E2 | 1 | Enable E2; set to 0 to disable |

Example without USRP support or the E2 agent:

```bash
OAI_HARDWARE=None OAI_BUILD_E2=0 ./scripts/build-oai.sh deps
OAI_HARDWARE=None OAI_BUILD_E2=0 ./scripts/build-oai.sh gnb
```

Building a gNB does not configure CU/DU roles or start the radio network.
Runtime configuration and hardware setup are separate steps.
This script does not build OAI CN5G or an O-RU.

## FlexRIC

Run from the project root, one command at a time:

```bash
./scripts/build-flexric.sh deps
./scripts/build-flexric.sh build
./scripts/build-flexric.sh install
```

The deps action installs system packages using apt.
It installs database development libraries, not a MySQL server.
It uses the distribution's SWIG package; verify its version against
the checked-out FlexRIC requirements before building.

| Variable | Default | Purpose |
| --- | --- | --- |
| FLEXRIC_SOURCE | PROJECT_ROOT/flexric | Local source directory |
| FLEXRIC_BUILD_DIR | FLEXRIC_SOURCE/build-local | CMake build directory |
| FLEXRIC_INSTALL_PREFIX | /usr/local | Installation prefix |
| BUILD_JOBS | 2 | Maximum build parallelism |
| E2AP_VERSION | E2AP_V2 | E2AP protocol version |
| KPM_VERSION | KPM_V3_00 | KPM service model version |
| XAPP_DB | MYSQL_XAPP | MYSQL_XAPP, SQLITE3_XAPP, or NONE_XAPP |

Use matching options for dependency installation and compilation.
For example, to select SQLite:

```bash
XAPP_DB=SQLITE3_XAPP ./scripts/build-flexric.sh deps
XAPP_DB=SQLITE3_XAPP ./scripts/build-flexric.sh build
./scripts/build-flexric.sh install
```

The install action builds the existing CMake configuration, then installs it.
Its configuration comes from the build directory's CMake cache.
Installed paths are recorded in build-local/install_manifest.txt.

OAI and FlexRIC E2AP/service-model versions must be compatible.
The defaults above reflect FlexRIC's checked-out configuration;
they do not establish compatibility with the downloaded OAI revision.

## UHD local source preparation

Run from the project root. UHD sources are retained locally.

- Repository: https://github.com/EttusResearch/uhd.git
- Tag: v4.8.0.0
- Commit: 308126a479ca19dfaebfe4784b375e608788d763
- Source directory: third_party/uhd/src
- Patch: oai/cmake_targets/tools/uhd-4.5plus-tdd-patch.diff

For a fresh workspace:

```bash
git clone --branch v4.8.0.0 --depth 1 \
  https://github.com/EttusResearch/uhd.git third_party/uhd/src
git -C third_party/uhd/src apply --check \
  "$PWD/oai/cmake_targets/tools/uhd-4.5plus-tdd-patch.diff"
git -C third_party/uhd/src apply \
  "$PWD/oai/cmake_targets/tools/uhd-4.5plus-tdd-patch.diff"
```

The patch has already been applied in the validated local workspace.
Do not apply it twice. A detached HEAD is expected when cloning a tag.

The upstream OAI installer builds UHD in /tmp/uhd and removes that directory.
The local build-uhd.sh script preserves both source and build directories.

## UHD build and installation

Run from the project root, one command at a time:

```bash
bash scripts/build-uhd.sh deps
bash scripts/build-uhd.sh build
bash scripts/build-uhd.sh install
/usr/local/bin/uhd_config_info --version
```

The validated build completed all 389 tasks.
The installed version reports UHD 4.8.0.HEAD-0-g308126a4.

| Variable | Default | Purpose |
| --- | --- | --- |
| UHD_SOURCE | PROJECT_ROOT/third_party/uhd/src | Local UHD source |
| UHD_BUILD_DIR | PROJECT_ROOT/third_party/uhd/build-local | Build directory |
| UHD_INSTALL_PREFIX | /usr/local | Installation prefix |
| BUILD_JOBS | 2 | Maximum build parallelism |

The script uses Ninja and a Release build.
Tests, examples, documentation, B100, USRP1, and USRP2 are disabled,
matching the inspected OAI helper options. OctoClock is enabled.
Installation invokes sudo and ldconfig.

Installed files are listed in third_party/uhd/build-local/install_manifest.txt.
No USRP hardware operation or FPGA/firmware image download was validated.

After installing local UHD, install remaining OAI dependencies with:

```bash
OAI_HARDWARE=None ./scripts/build-oai.sh deps
```

This skips OAI's USRP/UHD installation path. The gNB build still uses
OAI_HARDWARE=USRP by default and detected /usr/local/lib/libuhd.so.

## OAI E2 dependency

With OAI_BUILD_E2=1, the OAI build initializes its own FlexRIC submodule:

- Repository: https://github.com/duranta-project/flexric.git
- Directory: oai/openair2/E2AP/flexric
- Observed commit: d7a71285f3720fbc1487e9a86309eec5fb61a408

This submodule supplies OAI E2 Agent build dependencies.
The separately cloned project-root flexric directory supplies the
standalone RIC and xApps. The two source revisions differ.
Do not replace OAI's submodule with the standalone checkout without
checking compatibility.

## Post-build validation

Run from the project root:

```bash
ldd oai/cmake_targets/ran_build/build/nr-softmodem
ldd /usr/local/bin/flexric/ric/nearRT-RIC
cat /usr/local/etc/flexric/ric.conf
timeout --signal=INT 10s /usr/local/bin/flexric/ric/nearRT-RIC \
  -c /usr/local/etc/flexric/ric.conf
```

Both ldd checks resolved all direct dependencies.

The tested RIC configuration uses:
- Service models: /usr/local/lib/flexric/
- Listen address: 127.0.0.1
- E2 SCTP port: 36421
- E42 SCTP port: 36422

The RIC loaded eight service models and initialized both interfaces.
The timeout command sent SIGINT after ten seconds; exit status 124
normally indicates the timeout elapsed, not a startup failure.

This startup check does not validate agent registration, subscriptions,
xApp operation, or OAI CU/DU integration.

## OAI and standalone FlexRIC source download

For a fresh workspace, run from the project root before preparing UHD:

```bash
git clone --branch develop \
  https://gitlab.eurecom.fr/oai/openairinterface5g.git oai
git -C oai checkout f8f769592a7030be88ede4bb5ca66fa1ca6a80e0

git clone --branch br-flexric \
  https://gitlab.eurecom.fr/mosaic5g/flexric.git flexric
git -C flexric checkout 736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8
```

Checking out the recorded commits reproduces the source revisions used
in this lab. Branch heads may change over time.

The recommended execution order is:
1. Download OAI, standalone FlexRIC, and UHD sources.
2. Apply the OAI TDD patch to UHD once.
3. Build and install UHD.
4. Install remaining OAI dependencies with OAI_HARDWARE=None.
5. Build the OAI gNB with USRP and E2 support.
6. Install FlexRIC dependencies, build, and install FlexRIC.
7. Check dynamic libraries and perform the bounded RIC startup test.

The OAI dependency installer may download additional build dependencies.
This procedure is not a fully offline or completely pinned build.
