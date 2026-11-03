#!/usr/bin/env python3
"""Review retained UDP regression rounds and reject incorrect evidence."""
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


def negative_checks(review, dest):
    original_read = Path.read_text
    cases = (
        ("limited cap exceeded", "grant", "limited",
         "Observed UL per-slot allocation exceeds configured cap"),
        ("restoration missing", "grant", "restored",
         "restored phase did not exceed the limited cap"),
        ("receiver bytes inconsistent", "bytes", "limited",
         "UDP final byte counts or packet loss require review: limited"),
        ("grace marker missing", "grace", "limited",
         "Server grace evidence missing or duplicated: limited"),
        ("drain did not become quiet", "drain", "limited",
         "UDP receive drain evidence invalid: limited"),
    )
    results = []
    for label, kind, phase, expected in cases:
        if kind == "grant":
            selected = dest / f"gnb.ul-{phase}.after-load.log"
            previous = original_read(dest / f"gnb.ul-{phase}.before-load.log")
            current = original_read(selected)
            require(current.startswith(previous), "Original history mismatch")
            delta = current[len(previous):]
            if phase == "limited":
                changed = delta.replace("rb=[0..10)", "rb=[0..11)")
            else:
                changed = re.sub(
                    r"(UE PUSCH:[^\n]*?\brb=)\[\d+\.\.\d+\)",
                    r"\g<1>[0..10)", delta,
                )
            require(changed != delta, "Missing grant mutation anchor")
            replacement = previous + changed
        elif kind == "bytes":
            selected = dest / f"iperf-ul-{phase}.json"
            data = json.loads(original_read(selected))
            data["server_output_json"]["end"]["sum_received"]["bytes"] -= 1200
            replacement = json.dumps(data)
        else:
            selected = dest / f"traffic.{phase}.after-load.streams.json"
            before = json.loads(original_read(
                dest / f"traffic.{phase}.before-load.streams.json"
            ))
            after = json.loads(original_read(selected))
            require(after["stderr"].startswith(before["stderr"]),
                    "Original stderr history mismatch")
            delta = after["stderr"][len(before["stderr"]):]
            if kind == "grace":
                changed = delta.replace(
                    "LAB_IPERF_SERVER_GRACE seconds=180",
                    "REMOVED_SERVER_GRACE",
                )
            else:
                changed = delta.replace("quiet_reached=1", "quiet_reached=0")
            require(changed != delta, "Missing marker mutation anchor")
            after["stderr"] = before["stderr"] + changed
            replacement = json.dumps(after)

        def modified_read(path, *args, **kwargs):
            if path == selected:
                return replacement
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", modified_read):
            try:
                review(dest)
            except RuntimeError as error:
                require(str(error) == expected,
                        f"Wrong rejection for {label}: {error}")
            else:
                raise RuntimeError("Incorrect evidence accepted: " + label)
        print("PASS: rejected " + label, flush=True)
        results.append({"case": label, "rejected": True, "reason": expected})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, nargs="+", type=Path)
    args = parser.parse_args()
    paths = [path.resolve() for path in args.evidence]
    require(len(paths) == len(set(paths)), "Duplicate evidence directories")
    require(all(path.is_relative_to(BASE.resolve()) and path.is_dir()
                for path in paths), "Unexpected evidence directory")
    helper = ROOT / "test/ocudu/review-slice-online-udp-grants.py"
    require(helper.is_file(), "Missing UDP reviewer")
    review = runpy.run_path(str(helper))["review"]

    report = Path(tempfile.mkdtemp(
        prefix="ocudu-slice-udp-regression-", dir=BASE,
    ))
    report.chmod(0o700)
    summary = {"passed": False, "scope": "Retained UDP evidence and negative checks",
               "rounds": [], "containers_started": 0, "control_requests_sent": 0}
    print("Regression report:", report, flush=True)
    try:
        for index, dest in enumerate(paths, 1):
            print(f"\n=== Regression {index}/{len(paths)}: {dest.name} ===",
                  flush=True)
            result = review(dest)
            require(result.get("passed") is True, "Original evidence failed")
            negatives = negative_checks(review, dest)
            summary["rounds"].append({
                "evidence": dest.name, "review": result,
                "negative_checks": negatives,
            })
            print("PASS: evidence, grants and negative checks", flush=True)
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        output = report / "summary.json"
        output.write_text(json.dumps(summary, indent=2) + "\n")
        print("SAVED:", output, flush=True)
    print("Passed:", summary["passed"])


if __name__ == "__main__":
    main()
