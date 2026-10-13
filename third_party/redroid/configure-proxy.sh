#!/usr/bin/env bash
set -euo pipefail

REDROID_CONTAINER="${REDROID_CONTAINER:-redroid}"
UE_CONTAINER="${UE_CONTAINER:-nr_ue}"
CORE_NETWORK="${CORE_NETWORK:-docker_open5gs_default}"
UE_TUN_INTERFACE="${UE_TUN_INTERFACE:-uesimtun0}"

get_network_ip() {
    docker inspect "$1" | python3 -c '
import json, sys
network = json.load(sys.stdin)[0]["NetworkSettings"]["Networks"].get(sys.argv[1], {})
print(network.get("IPAddress", ""))
' "$CORE_NETWORK"
}

ue_ip="$(get_network_ip "$UE_CONTAINER")"
redroid_ip="$(get_network_ip "$REDROID_CONTAINER")"
if [[ -z "$ue_ip" || -z "$redroid_ip" ]]; then
    echo "Connect both containers to the core network first." >&2
    exit 1
fi

pdu_ip="$(docker exec "$UE_CONTAINER" ip -o -4 addr show dev "$UE_TUN_INTERFACE" |
    python3 -c '
import ipaddress, sys
lines = sys.stdin.read().splitlines()
if len(lines) != 1:
    raise SystemExit("Expected exactly one IPv4 address on the UE TUN interface.")
fields = lines[0].split()
print(ipaddress.ip_interface(fields[fields.index("inet") + 1]).ip)
')"

route="$(docker exec "$UE_CONTAINER" ip -4 route get 1.1.1.1 from "$pdu_ip")"
if [[ "$route" != *"dev $UE_TUN_INTERFACE "* ]]; then
    echo "The PDU source address does not route through $UE_TUN_INTERFACE." >&2
    echo "$route" >&2
    exit 1
fi

if ! docker exec "$UE_CONTAINER" sh -c 'command -v tinyproxy >/dev/null'; then
    echo "Install tinyproxy, curl, and ca-certificates in the UE container first." >&2
    exit 1
fi

docker exec -i "$UE_CONTAINER" sh -c '
set -eu
config=/etc/tinyproxy/tinyproxy.conf
backup=/etc/tinyproxy/tinyproxy.conf.before-redroid
if [ ! -e "$backup" ]; then
    cp -p "$config" "$backup"
fi
cat > "$config"
mkdir -p /run/tinyproxy /var/log/tinyproxy
chown tinyproxy:tinyproxy /run/tinyproxy /var/log/tinyproxy
' <<EOF
# Managed by third_party/redroid/configure-proxy.sh.
User tinyproxy
Group tinyproxy
Port 8888
Listen $ue_ip
Bind $pdu_ip
Timeout 600
LogFile "/var/log/tinyproxy/tinyproxy.log"
LogLevel Info
PidFile "/run/tinyproxy/tinyproxy.pid"
MaxClients 100
MinSpareServers 5
MaxSpareServers 20
StartServers 10
Allow 127.0.0.1
Allow $redroid_ip
Allow $ue_ip
ConnectPort 443
ConnectPort 563
EOF

docker exec "$UE_CONTAINER" service tinyproxy restart
docker exec "$REDROID_CONTAINER" /system/bin/settings put global http_proxy "$ue_ip:8888"

echo "Android proxy: $ue_ip:8888"
echo "Allowed ReDroid client: $redroid_ip"
echo "Proxy outgoing source address: $pdu_ip"
echo "Re-run this script after the UE PDU address changes."
