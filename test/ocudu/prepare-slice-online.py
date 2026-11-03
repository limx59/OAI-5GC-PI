#!/usr/bin/env python3
"""Prepare a single-cell configuration for online slice-control validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re


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

    source = root / "deploy/ocudu/config/gnb-zmq-e2.yml"
    require(source.resolve().is_relative_to(root) and source.is_file(),
            "Missing or unexpected base configuration")
    original = source.read_bytes()
    text = original.decode()

    require(not re.search(r"(?m)^\s*(?:slicing|remote_control)\s*:", text),
            "Unexpected existing slicing or remote-control configuration")

    for old, new in (
        ("  enable_du_e2: true", "  enable_du_e2: false"),
        ("  e2sm_kpm_enabled: true", "  e2sm_kpm_enabled: false"),
    ):
        text = once(text, old, new)

    for name in (
        "enable_cu_cp_e2", "enable_cu_up_e2", "enable_du_e2",
        "e2sm_kpm_enabled", "e2sm_rc_enabled", "e2sm_ccc_enabled",
    ):
        require(len(re.findall(
            r"(?m)^  " + re.escape(name) + r": false\s*$", text
        )) == 1, "Expected disabled flag: " + name)

    text = once(
        text,
        "  pci: 1\n",
        "  pci: 1\n"
        "  slicing:\n"
        "    - sst: 1\n"
        "      sched_cfg:\n"
        "        min_prb_policy_ratio: 0\n"
        "        max_prb_policy_ratio: 100\n",
    )
    text = once(
        text,
        "  all_level: info\n",
        "  all_level: info\n  mac_level: debug\n",
    )
    text += (
        "\nremote_control:\n"
        "  enabled: true\n"
        "  bind_addr: 127.0.0.1\n"
        "  port: 8001\n"
    )

    require(source.read_bytes() == original,
            "Base configuration changed during preparation")
    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    path = output / "gnb.yml"
    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        stream.write(text)

    return {
        "scope": "Single-cell online slice-control configuration only",
        "source": str(source.relative_to(root)),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "generated_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "e2_enabled": False,
        "remote_control": {
            "bind_addr": "127.0.0.1",
            "port": 8001,
            "host_port_published": False,
        },
        "slice": {
            "sst": 1,
            "sd": None,
            "min_prb_policy_ratio": 0,
            "max_prb_policy_ratio": 100,
        },
        "original_configuration_unchanged": True,
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
