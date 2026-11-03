#!/usr/bin/env python3
"""Run or review single-UE DL slice regressions with negative evidence checks."""
import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def negative_checks(review, dest):
    original_read = Path.read_text
    cases = (
        ("missing scheduler update", "limited",
         "- Slice Reconfig: cell=0", "- Removed update event",
         "Expected one scheduler update"),
        ("DL allocation exceeds limited cap", "limited",
         "rb=[0..10)", "rb=[0..11)",
         "Observed DL per-slot allocation exceeds configured cap"),
        ("restored allocation never exceeds former cap", "restored",
         "rb=[0..11)", "rb=[0..10)",
         "Restored phase did not exceed the former cap"),
        ("unexpected DL logical channel", "limited",
         "lcid=4:", "lcid=5:",
         "Unexpected or unclassified DL logical channel"),
    )
    results = []
    for label, phase, old, new, expected in cases:
        selected = dest / f"gnb.{phase}.after.log"
        previous = original_read(dest / f"gnb.{phase}.before.log")
        current = original_read(selected)
        require(current.startswith(previous), "Original log history mismatch")
        delta = current[len(previous):]
        marker = "- Slice Reconfig: cell=0"
        require(delta.count(marker) == 1, "Unexpected original event count")
        if old == marker:
            changed = previous + delta.replace(old, new, 1)
        else:
            leading, marker, trailing = delta.partition(marker)
            require(old in trailing, "Missing mutation anchor: " + label)
            changed = previous + leading + marker + trailing.replace(old, new)

        def modified_read(path, *args, **kwargs):
            if path == selected:
                return changed
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", modified_read):
            try:
                review(dest)
            except RuntimeError as error:
                require(str(error) == expected,
                        "Wrong rejection for " + label + ": " + str(error))
            else:
                raise RuntimeError("Incorrect evidence accepted: " + label)
        results.append({"case": label, "passed": True, "reason": expected})
        print("PASS: rejected " + label, flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rounds", type=int, choices=range(1, 4))
    mode.add_argument("--evidence", type=Path, nargs="+")
    args = parser.parse_args()

    helper = ROOT / "test/ocudu/review-slice-online-grants.py"
    runner = ROOT / "test/ocudu/validate-slice-online-control.py"
    for path in (helper, runner):
        require(path.resolve().is_relative_to(ROOT) and path.is_file(),
                "Missing or unexpected test script")
    review = runpy.run_path(str(helper))["review"]

    BASE.mkdir(parents=True, exist_ok=True)
    report = Path(tempfile.mkdtemp(prefix="ocudu-slice-regression-", dir=BASE))
    report.chmod(0o700)
    summary = {
        "passed": False,
        "mode": "live" if args.rounds else "retained-evidence",
        "scope": "Single-UE online DL slice cap and restoration",
        "ul_cap_effect_validated": False,
        "multi_agent_control_validated": False,
        "rounds": [],
    }
    print("Regression report:", report, flush=True)
    try:
        destinations = []
        if args.evidence:
            destinations = [path.resolve() for path in args.evidence]
            require(len(set(destinations)) == len(destinations),
                    "Duplicate evidence directories")
            for dest in destinations:
                require(dest.is_relative_to(BASE) and dest.is_dir(),
                        "Unexpected evidence directory")
        total = args.rounds or len(destinations)
        for number in range(total):
            record = {"number": number + 1, "passed": False}
            summary["rounds"].append(record)
            print(f"\n=== Regression {number + 1}/{total} ===", flush=True)
            if args.rounds:
                previous = set(BASE.glob("ocudu-slice-online-control-*"))
                completed = subprocess.run(
                    [sys.executable, "-B", str(runner)], check=False,
                )
                created = set(BASE.glob("ocudu-slice-online-control-*")) - previous
                require(len(created) == 1,
                        "Expected exactly one new evidence directory")
                dest = created.pop().resolve()
                record["evidence"] = dest.name
                require(completed.returncode == 0, "Online test failed")
            else:
                dest = destinations[number]
                record["evidence"] = dest.name

            result = review(dest)
            require(result.get("passed") is True, "Grant review failed")
            record["grant_review"] = result
            record["negative_checks"] = negative_checks(review, dest)
            record["passed"] = True
            print("PASS: online evidence, grants and negative checks: "
                  + dest.name, flush=True)
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        print("FAIL:", error, flush=True)
    finally:
        path = report / "summary.json"
        with path.open("x") as stream:
            stream.write(json.dumps(summary, indent=2) + "\n")
        print("\nPassed:", summary["passed"], flush=True)
        print("SAVED:", path, flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
