#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

if [[ "$(getconf PAGESIZE)" != "4096" ]]; then
    echo "This deployment requires 4 KB memory pages. Follow the README to switch kernels and reboot." >&2
    exit 1
fi

# Load modules required by Open5GS and UERANSIM, including SCTP's MD5 dependency.
for module in md5 sctp tun iptable_nat iptable_filter ip6table_nat ip6table_filter; do
    modprobe "$module"
done

# binder_linux is built into the current Raspberry Pi kernel.
mkdir -p /dev/binderfs
if mountpoint -q /dev/binderfs; then
    if [[ "$(findmnt -rn -M /dev/binderfs -o FSTYPE)" != "binder" ]]; then
        echo "/dev/binderfs is occupied by another filesystem. Check the existing mount." >&2
        exit 1
    fi
else
    mount -t binder binder /dev/binderfs
fi

for device in binder hwbinder vndbinder; do
    path="/dev/binderfs/$device"
    if [[ ! -c "$path" ]]; then
        echo "Missing Binder character device: $path" >&2
        exit 1
    fi
    # Android services run under different UIDs and require Binder access.
    chmod 0666 "$path"
done

echo "Host preparation complete: 4 KB memory pages, kernel modules, and Binder devices are ready."
