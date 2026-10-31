#!/usr/bin/env python3
"""Generate private dual-OCUDU configurations without changing originals."""

import argparse
import os
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def once(text, old, new):
    require(text.count(old) == 1, f"Unexpected non-secret anchor: {old}")
    return text.replace(old, new, 1)


def field(text, key):
    matches = list(re.finditer(
        rf'(?m)^(\s*{re.escape(key)}\s*=\s*)"([^"\n]+)"(\s*;)',
        text,
    ))
    require(len(matches) == 1, f"Expected one private field: {key}")
    return matches[0]


def prepare(root, output):
    require(not output.exists(), "Output directory already exists")
    gnb = (root / "deploy/ocudu/config/gnb-zmq-e2.yml").read_text()
    ue = (root / "deploy/ocudu/.local/ue-zmq.conf").read_text()
    second = (root / "deploy/oai-flexric/config/oai/ue-2.conf").read_text()
    require(field(ue, "imsi").group(2) != field(second, "imsi").group(2),
            "Two distinct subscriptions required")
    ue_second = ue
    for key in ("imsi", "key", "opc"):
        original = field(ue_second, key)
        replacement = field(second, key).group(2)
        ue_second = (
            ue_second[:original.start(2)] + replacement
            + ue_second[original.end(2):]
        )
    sessions = r"(?m)^\s*pdu_sessions\s*=.*$"
    a, b = re.findall(sessions, ue), re.findall(sessions, second)
    require(len(a) == len(b) == 1 and a[0].strip() == b[0].strip(),
            "Existing UE session settings must match")
    require("172.22.0.160" in ue_second,
            "Expected ZeroMQ peer address missing")
    ue_second = ue_second.replace("172.22.0.160", "172.22.0.164")
    ue_second = ue_second.replace("172.22.0.161", "172.22.0.165")

    require(not re.search(r"(?m)^buffer_pool:", gnb),
            "Unexpected existing buffer-pool section")
    gnb += (
        "\n# Bounded dual-node memory experiment; default segment size retained.\n"
        "buffer_pool:\n"
        "  nof_segments: 65536\n"
    )
    gnb = once(gnb, "  addrs: [172.22.0.162]",
               "  addrs: [172.22.0.163]")
    gnb_second = gnb.replace("172.22.0.160", "172.22.0.164")
    gnb_second = gnb_second.replace("172.22.0.161", "172.22.0.165")
    gnb_second = once(gnb_second, "gnb_id: 420", "gnb_id: 421")
    # Single-variable diagnostic: retain PCI 1 on independent ZMQ links.
    require(gnb_second.count("  pci: 1") == 1,
            "Expected PCI 1 anchor missing")
    gnb_second = once(
        gnb_second, "ran_node_name: ocudu-pi-zmq",
        "ran_node_name: ocudu-pi-zmq-2",
    )
    files = {
        "gnb-1.yml": gnb, "gnb-2.yml": gnb_second,
        "ue-1.conf": ue, "ue-2.conf": ue_second,
    }
    for filename in ("ric.conf", "xapp.conf"):
        text = (root / "deploy/ocudu/config" / filename).read_text()
        files[filename] = once(
            text, 'NearRT_RIC_IP = "172.22.0.162"',
            'NearRT_RIC_IP = "172.22.0.163"',
        )
    output.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    for name, text in files.items():
        with open(output / name, "x", opener=lambda p, flags:
                                 os.open(p, flags, 0o600)) as stream:
            stream.write(text)
    return {
        "node_ids": [420, 421],
        "pci_values": [1, 1],
        "diagnostic": "PCI-only control on independent ZeroMQ links",
        "gnb_addresses": ["172.22.0.160", "172.22.0.164"],
        "ue_addresses": ["172.22.0.161", "172.22.0.165"],
        "ric_address": "172.22.0.163",
        "distinct_subscriptions": True,
        "buffer_pool_segments_per_gnb": 65536,
        "default_buffer_pool_segments": 1048576,
        "original_files_modified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    prepare(root, args.output.resolve())
    print("PASS: private dual-node configuration generated.")
    print("Original files unchanged; credentials not displayed.")


if __name__ == "__main__":
    main()
