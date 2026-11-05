#!/usr/bin/env python3
"""Prepare a private single-UE configuration for session stability checks."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import json


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def prepare(root, output):
    root = root.resolve()
    output = output.resolve()
    require(output.is_relative_to(root) and not output.exists(),
            "Output exists or outside repository")
    source = root / "deploy/ocudu/config/gnb-zmq.yml"
    require(source.resolve().is_relative_to(root) and source.is_file(),
            "Missing base configuration")
    original = source.read_bytes()
    text = original.decode()
    require(not re.search(
        r"(?m)^\s*(?:test_mode|remote_control)\s*:", text),
        "Unexpected testmode or remote-control configuration")

    for name in ("all_level", "radio_level", "phy_level"):
        old = f"  {name}: debug\n"
        require(text.count(old) == 1,
                "Unexpected logging configuration: " + name)
        text = text.replace(old, f"  {name}: info\n", 1)

    require(not re.search(r"(?m)^expert_execution\s*:", text),
            "Unexpected existing expert_execution configuration")
    text = text.rstrip() + """

# Explicit two-worker main pool for the ZMQ session.
expert_execution:
  threads:
    main_pool:
      nof_threads: 2
"""

    require(source.read_bytes() == original,
            "Base configuration changed during preparation")
    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    path = output / "gnb.yml"
    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        stream.write(text)

    return {
        "scope": "Single-UE ZMQ session stability configuration",
        "source": str(source.relative_to(root)),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "generated_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "original_configuration_unchanged": True,
        "log_level": "info",
        "main_pool_threads": 2,
        "live_session_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    print(json.dumps(prepare(root, args.output), indent=2))


if __name__ == "__main__":
    main()
