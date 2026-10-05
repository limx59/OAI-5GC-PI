#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FLEXRIC_SOURCE="${FLEXRIC_SOURCE:-$PROJECT_ROOT/flexric}"
FLEXRIC_BUILD_DIR="${FLEXRIC_BUILD_DIR:-$FLEXRIC_SOURCE/build-local}"
FLEXRIC_INSTALL_PREFIX="${FLEXRIC_INSTALL_PREFIX:-/usr/local}"
BUILD_JOBS="${BUILD_JOBS:-2}"
E2AP_VERSION="${E2AP_VERSION:-E2AP_V2}"
KPM_VERSION="${KPM_VERSION:-KPM_V3_00}"
XAPP_DB="${XAPP_DB:-MYSQL_XAPP}"
ACTION="${1:-help}"

case "$ACTION" in
    deps|build|install) ;;
    help|--help|-h)
        echo "Usage: $0 {deps|build|install}"
        echo "Environment: FLEXRIC_SOURCE, FLEXRIC_BUILD_DIR,"
        echo "  FLEXRIC_INSTALL_PREFIX, BUILD_JOBS, E2AP_VERSION, KPM_VERSION, XAPP_DB"
        exit 0
        ;;
    *)
        echo "Unknown action: $ACTION" >&2
        exit 1
        ;;
esac

if [[ ! "$BUILD_JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "BUILD_JOBS must be a positive integer." >&2
    exit 1
fi
case "$E2AP_VERSION" in
    E2AP_V1|E2AP_V2|E2AP_V3) ;;
    *) echo "Invalid E2AP_VERSION: $E2AP_VERSION" >&2; exit 1 ;;
esac
case "$KPM_VERSION" in
    KPM_V2_01|KPM_V2_03|KPM_V3_00) ;;
    *) echo "Invalid KPM_VERSION: $KPM_VERSION" >&2; exit 1 ;;
esac
case "$XAPP_DB" in
    MYSQL_XAPP|SQLITE3_XAPP|NONE_XAPP) ;;
    *) echo "Invalid XAPP_DB: $XAPP_DB" >&2; exit 1 ;;
esac

if [[ "$ACTION" == deps ]]; then
    command -v apt-get >/dev/null || {
        echo "Dependency installation requires an apt-based distribution." >&2
        exit 1
    }
    packages=(
        build-essential git cmake cmake-curses-gui pkg-config
        autoconf automake libtool bison libpcre2-dev
        libsctp-dev python3 python3-dev swig
        libconfig-dev libconfig++-dev
    )
    case "$XAPP_DB" in
        MYSQL_XAPP) packages+=(default-libmysqlclient-dev) ;;
        SQLITE3_XAPP) packages+=(libsqlite3-dev) ;;
    esac
    sudo apt-get update
    sudo apt-get install -y "${packages[@]}"
    exit 0
fi

if [[ $EUID -eq 0 ]]; then
    echo "Run as a regular user; the install action invokes sudo." >&2
    exit 1
fi
if [[ ! -f "$FLEXRIC_SOURCE/CMakeLists.txt" ]]; then
    echo "FlexRIC source not found: $FLEXRIC_SOURCE" >&2
    exit 1
fi
command -v cmake >/dev/null || {
    echo "CMake is missing. Run the deps action first." >&2
    exit 1
}

if [[ "$ACTION" == build ]]; then
    cmake -S "$FLEXRIC_SOURCE" -B "$FLEXRIC_BUILD_DIR" \
        -DCMAKE_INSTALL_PREFIX="$FLEXRIC_INSTALL_PREFIX" \
        -DE2AP_VERSION="$E2AP_VERSION" \
        -DKPM_VERSION="$KPM_VERSION" \
        -DXAPP_DB="$XAPP_DB"
    cmake --build "$FLEXRIC_BUILD_DIR" --parallel "$BUILD_JOBS"
    echo "Build completed: $FLEXRIC_BUILD_DIR"
else
    if [[ ! -f "$FLEXRIC_BUILD_DIR/CMakeCache.txt" ]]; then
        echo "Build directory is not configured. Run the build action first." >&2
        exit 1
    fi
    cmake --build "$FLEXRIC_BUILD_DIR" --parallel "$BUILD_JOBS"
    sudo cmake --install "$FLEXRIC_BUILD_DIR"
    echo "Installation completed. See $FLEXRIC_BUILD_DIR/install_manifest.txt."
fi
