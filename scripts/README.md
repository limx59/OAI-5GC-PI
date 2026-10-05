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

Shell syntax checks and help commands passed.
Compilation, installation, and OAI/FlexRIC interoperability have not yet
been validated with these scripts.

The checked OAI build helper lists Ubuntu 22-24, Fedora, and RHEL9.
Raspberry Pi OS compatibility still requires verification.

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
./scripts/build-oai.sh deps
./scripts/build-oai.sh gnb
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
