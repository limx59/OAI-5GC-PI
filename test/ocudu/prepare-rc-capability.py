#!/usr/bin/env python3
"""Prepare private single-node CU-CP RC discovery configuration."""
import argparse
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
    require(output.is_relative_to(root), "Output outside review repository")
    require(not output.exists(), "Output directory already exists")
    inputs = {
        "gnb-1.yml": "deploy/ocudu/config/gnb-zmq-e2.yml",
        "ue-1.conf": "deploy/ocudu/.local/ue-zmq.conf",
        "ric.conf": "deploy/ocudu/config/ric.conf",
        "xapp.conf": "deploy/ocudu/config/xapp.conf",
    }
    files = {}
    for name, relative in inputs.items():
        source = root / relative
        require(source.resolve().is_relative_to(root) and source.is_file(),
                "Input missing or outside review repository: " + relative)
        files[name] = source.read_text()

    gnb = files["gnb-1.yml"]
    for old, new in (
        ("  enable_cu_cp_e2: false", "  enable_cu_cp_e2: true"),
        ("  enable_du_e2: true", "  enable_du_e2: false"),
        ("  e2sm_kpm_enabled: true", "  e2sm_kpm_enabled: false"),
        ("  e2sm_rc_enabled: false", "  e2sm_rc_enabled: true"),
        ("  addrs: [172.22.0.162]", "  addrs: [172.22.0.163]"),
    ):
        gnb = once(gnb, old, new)
    require(gnb.count("  enable_cu_up_e2: false") == 1,
            "CU-UP E2 must remain disabled")
    require(gnb.count("  e2sm_ccc_enabled: false") == 1,
            "CCC must remain disabled")
    require(re.search(r"(?m)^gnb_id:\s*420\s*$", gnb),
            "Expected laboratory node 420")
    require(not re.search(r"(?m)^buffer_pool:", gnb),
            "Unexpected buffer-pool section")
    files["gnb-1.yml"] = gnb + (
        "\nbuffer_pool:\n  nof_segments: 65536\n"
    )
    for name in ("ric.conf", "xapp.conf"):
        files[name] = once(
            files[name], 'NearRT_RIC_IP = "172.22.0.162"',
            'NearRT_RIC_IP = "172.22.0.163"',
        )

    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    for name, text in files.items():
        with open(output / name, "x", opener=lambda p, flags:
                  os.open(p, flags, 0o600)) as stream:
            stream.write(text)
    return {
        "node_id": 420,
        "cu_cp_e2_enabled": True,
        "du_e2_enabled": False,
        "cu_up_e2_enabled": False,
        "rc_enabled": True,
        "kpm_enabled": False,
        "control_requests_enabled": False,
        "original_files_modified": False,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    prepare(root, args.output)
    print("PASS: private CU-CP RC discovery configuration generated.")

if __name__ == "__main__":
    main()
