#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OAI_SOURCE="${OAI_SOURCE:-$PROJECT_ROOT/oai}"
BUILD_JOBS="${BUILD_JOBS:-2}"
OAI_HARDWARE="${OAI_HARDWARE:-USRP}"
OAI_BUILD_E2="${OAI_BUILD_E2:-1}"
ACTION="${1:-help}"

case "$ACTION" in
    deps|gnb|nrue) ;;
    help|--help|-h)
        echo "Usage: $0 {deps|gnb|nrue}"
        echo "Environment: OAI_SOURCE, BUILD_JOBS, OAI_HARDWARE, OAI_BUILD_E2"
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
if [[ "$OAI_BUILD_E2" != 0 && "$OAI_BUILD_E2" != 1 ]]; then
    echo "OAI_BUILD_E2 must be 0 or 1." >&2
    exit 1
fi
if [[ ! -x "$OAI_SOURCE/cmake_targets/build_oai" ]]; then
    echo "OAI build script not found: $OAI_SOURCE/cmake_targets/build_oai" >&2
    exit 1
fi
if [[ $EUID -eq 0 ]]; then
    echo "Run as a regular user; dependency installation may invoke sudo." >&2
    exit 1
fi

cd "$OAI_SOURCE"
if [[ -f oaienv ]]; then
    set +u
    source ./oaienv
    set -u
fi
cd cmake_targets

if [[ "$ACTION" == deps ]]; then
    exec ./build_oai -I -w "$OAI_HARDWARE"
fi

args=(--ninja -w "$OAI_HARDWARE" --build-tool-opt "-j$BUILD_JOBS")
case "$ACTION" in
    gnb) args+=(--gNB) ;;
    nrue) args+=(--nrUE) ;;
esac
if [[ "$OAI_BUILD_E2" == 1 ]]; then
    args+=(--build-e2)
fi

printf 'Running:'
printf ' %q' ./build_oai "${args[@]}"
printf '\n'
exec ./build_oai "${args[@]}"
