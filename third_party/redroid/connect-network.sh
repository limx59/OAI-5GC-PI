#!/usr/bin/env bash
set -euo pipefail

REDROID_CONTAINER="${REDROID_CONTAINER:-redroid}"
UE_CONTAINER="${UE_CONTAINER:-nr_ue}"
CORE_NETWORK="${CORE_NETWORK:-docker_open5gs_default}"

get_network_ip() {
    docker inspect "$1" | python3 -c '
import json, sys
container = json.load(sys.stdin)[0]
network = container["NetworkSettings"]["Networks"].get(sys.argv[1], {})
print(network.get("IPAddress", ""))
' "$CORE_NETWORK"
}

for container in "$REDROID_CONTAINER" "$UE_CONTAINER"; do
    if [[ "$(docker inspect --format '{{.State.Running}}' "$container")" != "true" ]]; then
        echo "Container is not running: $container" >&2
        exit 1
    fi
done

boot_completed="$(docker exec "$REDROID_CONTAINER" /system/bin/getprop sys.boot_completed)"
if [[ "${boot_completed//$'\r'/}" != "1" ]]; then
    echo "Android has not completed booting. Retry after boot completes." >&2
    exit 1
fi

docker network inspect "$CORE_NETWORK" >/dev/null
ue_ip="$(get_network_ip "$UE_CONTAINER")"
if [[ -z "$ue_ip" ]]; then
    echo "UE container is not connected to $CORE_NETWORK." >&2
    exit 1
fi

redroid_ip="$(get_network_ip "$REDROID_CONTAINER")"
if [[ -z "$redroid_ip" ]]; then
    docker network connect "$CORE_NETWORK" "$REDROID_CONTAINER"
    redroid_ip="$(get_network_ip "$REDROID_CONTAINER")"
fi

if [[ -z "$redroid_ip" ]]; then
    echo "Failed to obtain the ReDroid address on $CORE_NETWORK." >&2
    exit 1
fi

# Android uses policy routing and may otherwise send this traffic through eth0.
# Replace only our destination-specific rule; preserve other Android rules.
while docker exec "$REDROID_CONTAINER" /system/bin/ip -4 rule del \
    priority 9000 to "$ue_ip/32" lookup main 2>/dev/null; do
    :
done

docker exec "$REDROID_CONTAINER" /system/bin/ip -4 rule add \
    priority 9000 to "$ue_ip/32" lookup main

echo "ReDroid address: $redroid_ip"
echo "UE proxy address: $ue_ip"
docker exec "$REDROID_CONTAINER" /system/bin/ip -4 route get "$ue_ip"
echo "Network configuration complete. Configure the UE proxy next."
