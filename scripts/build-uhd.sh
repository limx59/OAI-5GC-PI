#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UHD_SOURCE="${UHD_SOURCE:-$PROJECT_ROOT/third_party/uhd/src}"
UHD_BUILD_DIR="${UHD_BUILD_DIR:-$PROJECT_ROOT/third_party/uhd/build-local}"
UHD_INSTALL_PREFIX="${UHD_INSTALL_PREFIX:-/usr/local}"
BUILD_JOBS="${BUILD_JOBS:-2}"
ACTION="${1:-help}"

case "$ACTION" in
    deps|build|install) ;;
    help|--help|-h)
        echo "Usage: $0 {deps|build|install}"
        echo "Environment: UHD_SOURCE, UHD_BUILD_DIR, UHD_INSTALL_PREFIX, BUILD_JOBS"
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
if [[ $EUID -eq 0 ]]; then
    echo "Run as a regular user; dependency installation and install invoke sudo." >&2
    exit 1
fi

if [[ "$ACTION" == deps ]]; then
    command -v apt-get >/dev/null || {
        echo "Dependency installation requires an apt-based distribution." >&2
        exit 1
    }
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build pkg-config \
        libboost-chrono-dev libboost-date-time-dev \
        libboost-filesystem-dev libboost-program-options-dev \
        libboost-thread-dev libboost-test-dev libboost-regex-dev \
        libusb-1.0-0-dev python3 python3-dev python3-mako \
        python3-numpy python3-requests python3-setuptools
    exit 0
fi

if [[ ! -f "$UHD_SOURCE/host/CMakeLists.txt" ]]; then
    echo "UHD host source not found: $UHD_SOURCE/host" >&2
    exit 1
fi
for tool in cmake ninja; do
    command -v "$tool" >/dev/null || {
        echo "Missing build tool: $tool. Run the deps action first." >&2
        exit 1
    }
done

if [[ "$ACTION" == build ]]; then
    cmake -S "$UHD_SOURCE/host" -B "$UHD_BUILD_DIR" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$UHD_INSTALL_PREFIX" \
        -DENABLE_TESTS=OFF \
        -DENABLE_EXAMPLES=OFF \
        -DENABLE_B100=OFF \
        -DENABLE_DOXYGEN=OFF \
        -DENABLE_MANUAL=OFF \
        -DENABLE_MAN_PAGES=OFF \
        -DENABLE_MAN_PAGE_COMPRESSION=OFF \
        -DENABLE_OCTOCLOCK=ON \
        -DENABLE_USRP1=OFF \
        -DENABLE_USRP2=OFF
    cmake --build "$UHD_BUILD_DIR" --parallel "$BUILD_JOBS"
    echo "Build completed: $UHD_BUILD_DIR"
else
    if [[ ! -f "$UHD_BUILD_DIR/CMakeCache.txt" ]]; then
        echo "Build directory is not configured. Run the build action first." >&2
        exit 1
    fi
    cmake --build "$UHD_BUILD_DIR" --parallel "$BUILD_JOBS"
    sudo cmake --install "$UHD_BUILD_DIR"
    sudo ldconfig
    echo "Installation completed. See $UHD_BUILD_DIR/install_manifest.txt."
fi
