#!/usr/bin/env python3
"""Prepare isolated OCUDU slicing configurations for dry-run validation."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected configuration anchor: " + old)
    return text.replace(old, new, 1)


def prepare(root, output):
    root = root.resolve()
    output = output.resolve()
    if not output.is_relative_to(root) or output.exists():
        raise RuntimeError("Output exists or outside repository")
    source = root / "deploy/ocudu/config/gnb-zmq-e2.yml"
    if not source.resolve().is_relative_to(root) or not source.is_file():
        raise RuntimeError("Missing or unexpected base configuration")

    original = source.read_bytes()
    base = original.decode()
    if re.search(r"(?m)^\s*slicing\s*:", base):
        raise RuntimeError("Unexpected existing slicing configuration")
    for old, new in (
        ("  enable_du_e2: true", "  enable_du_e2: false"),
        ("  e2sm_kpm_enabled: true", "  e2sm_kpm_enabled: false"),
    ):
        base = once(base, old, new)
    for setting in (
        "enable_cu_cp_e2", "enable_cu_up_e2", "enable_du_e2",
        "e2sm_kpm_enabled", "e2sm_rc_enabled", "e2sm_ccc_enabled",
    ):
        if len(re.findall(r"(?m)^  " + setting + r": false\s*$", base)) != 1:
            raise RuntimeError("Expected disabled setting: " + setting)

    valid = once(
        base,
        "            tai_slice_support_list:\n"
        "              - sst: 1\n",
        "            tai_slice_support_list:\n"
        "              - sst: 1\n"
        "                sd: 1\n"
        "              - sst: 2\n"
        "                sd: 42\n",
    )
    valid = once(
        valid, "cell_cfg:\n",
        "cell_cfg:\n"
        "  slicing:\n"
        "    - sst: 1\n"
        "      sd: 1\n"
        "      sched_cfg:\n"
        "        min_prb_policy_ratio: 20\n"
        "        max_prb_policy_ratio: 40\n"
        "    - sst: 2\n"
        "      sd: 42\n"
        "      sched_cfg:\n"
        "        min_prb_policy_ratio: 20\n"
        "        max_prb_policy_ratio: 60\n",
    )
    invalid = once(
        valid,
        "        min_prb_policy_ratio: 20\n"
        "        max_prb_policy_ratio: 40\n",
        "        min_prb_policy_ratio: 80\n"
        "        max_prb_policy_ratio: 40\n",
    )
    files = {
        "baseline.yml": base,
        "two-slices.yml": valid,
        "invalid-min-max.yml": invalid,
    }
    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    for name, text in files.items():
        path = output / name
        with path.open("x") as stream:
            stream.write(text)
        path.chmod(0o600)
    return {
        "scope": "Configuration dry-run only; no scheduling validation",
        "source": str(source.relative_to(root)),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "files": list(files),
        "e2_enabled": False,
        "slices": [
            {"sst": 1, "sd": 1, "min_ratio": 20, "max_ratio": 40},
            {"sst": 2, "sd": 42, "min_ratio": 20, "max_ratio": 60},
        ],
        "negative_case": "First slice min=80 exceeds max=40",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    print(json.dumps(prepare(root, args.output), indent=2))


if __name__ == "__main__":
    main()
