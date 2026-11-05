#!/usr/bin/env python3
"""Reject targeted mutations of parsed testmode and historical linkage evidence."""
import argparse
import json
from pathlib import Path
import re
import runpy
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate(dest):
    dest = dest.resolve()
    review = runpy.run_path(str(
        ROOT / "test/ocudu/review-testmode-state.py"
    ))["review"]
    original = review(dest)
    original_read = Path.read_text
    summary = json.loads(original_read(dest / "summary.json"))
    historical = BASE / summary["retained_real_ue"]["evidence"]
    cases = (
        ("wrong parsed state", "state", "Parsed testmode state mismatch"),
        ("missing validation marker", "marker", "Invalid validation/state markers"),
        ("changed configuration", "config", "Configuration hash mismatch"),
        ("wrong historical linkage", "link", "Historical configuration linkage mismatch"),
        ("failed UPF ping", "ping", "Historical UPF ping evidence failed"),
        ("testmode true in historical log", "flag",
         "Historical testmode log flags require review"),
    )
    checks = []
    for label, kind, expected in cases:
        overrides = {}
        if kind in ("state", "marker"):
            changed = False
            for name in ("stdout.log", "stderr.log"):
                path = dest / "default" / name
                text = original_read(path)
                old = ("du_enabled=false" if kind == "state"
                       else "LAB_CONFIG_VALIDATION_PASSED")
                if old in text:
                    replacement = ("du_enabled=true" if kind == "state"
                                   else "REMOVED_VALIDATION_MARKER")
                    overrides[path] = text.replace(old, replacement, 1)
                    changed = True
                    break
            require(changed, "Mutation anchor missing")
        elif kind == "config":
            path = dest / "default/gnb.yml"
            overrides[path] = original_read(path) + "\n# altered evidence\n"
        elif kind == "link":
            path = dest / "summary.json"
            value = json.loads(original_read(path))
            value["retained_real_ue"]["configuration_sha256"] = "0" * 64
            overrides[path] = json.dumps(value)
        elif kind == "ping":
            overrides[historical / "ping-before-control.log"] = (
                "5 packets transmitted, 4 received, 20% packet loss\n"
            )
        else:
            path = historical / "gnb.final.log"
            text = original_read(path)
            changed, count = re.subn(
                r'(["\']?test_mode["\']?\s*[:=]\s*)false\b',
                lambda match: match[1] + "true", text, count=1, flags=re.I,
            )
            require(count == 1, "Historical flag mutation anchor missing")
            overrides[path] = changed

        def mutated(path, *args, **kwargs):
            resolved = path.resolve()
            if resolved in overrides:
                return overrides[resolved]
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", mutated):
            try:
                review(dest)
            except RuntimeError as error:
                require(str(error) == expected,
                        f"Unexpected rejection for {label}: {error}")
            else:
                raise RuntimeError("Incorrect evidence accepted: " + label)
        checks.append({"case": label, "rejected": True, "reason": expected})
        print("PASS: rejected", label)
    return {"review": original, "negative_checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.evidence)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-testmode-evidence-", dir=BASE))
    dest.chmod(0o700)
    path = dest / "summary.json"
    with path.open("x") as stream:
        path.chmod(0o600)
        json.dump({"passed": True, **result}, stream, indent=2)
        stream.write("\n")
    print("SAVED:", path)
    print("PASS: six negative checks; original evidence unchanged.")


if __name__ == "__main__":
    main()
