#!/usr/bin/env python3
"""Prepare private dual-node configurations for lab slice coordination."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def once(text, old, new):
    require(text.count(old) == 1, "Unexpected configuration anchor: " + old)
    return text.replace(old, new, 1)


def prepare(root, output):
    root = root.resolve()
    output = output.resolve()
    require(output.is_relative_to(root) and not output.exists(),
            "Output exists or outside repository")
    names = (
        "test/ocudu/prepare-steering-dual-node-pci-control.py",
        "deploy/ocudu/config/gnb-zmq-e2.yml",
        "deploy/ocudu/.local/ue-zmq.conf",
        "deploy/oai-flexric/config/oai/ue-2.conf",
        "deploy/ocudu/config/ric.conf",
        "deploy/ocudu/config/xapp.conf",
    )
    originals = {}
    for name in names:
        path = root / name
        require(path.resolve().is_relative_to(root) and path.is_file(),
                "Missing or unexpected input: " + name)
        originals[name] = path.read_bytes()

    helper = runpy.run_path(str(root / names[0]))
    metadata = helper["prepare"](root, output)
    generated = {}
    for index, node in ((1, 420), (2, 421)):
        path = output / f"gnb-{index}.yml"
        text = path.read_text()
        require(re.search(rf"(?m)^gnb_id: {node}\s*$", text),
                "Unexpected generated node identity")
        require(not re.search(
            r"(?m)^\s*(?:slicing|remote_control)\s*:", text
        ), "Unexpected existing slicing or remote-control section")

        text = once(text, "  enable_du_e2: true",
                    "  enable_du_e2: false")
        text = once(text, "  e2sm_kpm_enabled: true",
                    "  e2sm_kpm_enabled: false")
        for flag in (
            "enable_cu_cp_e2", "enable_cu_up_e2", "enable_du_e2",
            "e2sm_kpm_enabled", "e2sm_rc_enabled", "e2sm_ccc_enabled",
        ):
            require(len(re.findall(
                rf"(?m)^  {flag}: false\s*$", text
            )) == 1, "Expected disabled flag: " + flag)

        text = once(
            text, "  pci: 1\n",
            "  pci: 1\n"
            "  slicing:\n"
            "    - sst: 1\n"
            "      sched_cfg:\n"
            "        min_prb_policy_ratio: 0\n"
            "        max_prb_policy_ratio: 100\n",
        )
        text = once(text, "  all_level: info\n",
                    "  all_level: info\n  mac_level: debug\n")
        text += (
            "\nremote_control:\n"
            "  enabled: true\n"
            "  bind_addr: 127.0.0.1\n"
            "  port: 8001\n"
        )
        require(text.count("  nof_segments: 65536") == 1,
                "Unexpected buffer-pool budget")
        generated[path.name] = text

    for name, text in generated.items():
        path = output / name
        path.write_text(text)
        os.chmod(path, 0o600)

    for name, original in originals.items():
        require((root / name).read_bytes() == original,
                "Input changed during preparation: " + name)

    return {
        "scope": "Dual-node WebSocket slice coordination configuration",
        "node_ids": metadata["node_ids"],
        "gnb_addresses": metadata["gnb_addresses"],
        "ue_addresses": metadata["ue_addresses"],
        "distinct_subscriptions": metadata["distinct_subscriptions"],
        "buffer_pool_segments_per_gnb": 65536,
        "e2_enabled": False,
        "remote_control": {
            "bind_addr": "127.0.0.1",
            "port_per_container": 8001,
            "host_port_published": False,
        },
        "slice": {
            "sst": 1, "sd": None,
            "min_prb_policy_ratio": 0,
            "max_prb_policy_ratio": 100,
        },
        "gnb_configuration_sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in generated
        },
        "original_files_modified": False,
        "live_scheduling_validated": False,
        "multi_agent_control_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    print(json.dumps(prepare(root, args.output), indent=2))


if __name__ == "__main__":
    main()
