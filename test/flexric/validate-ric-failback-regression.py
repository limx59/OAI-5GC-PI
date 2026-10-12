#!/usr/bin/env python3
"""Run three proactive RIC failback rounds and archive verified evidence."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-ric-failback-regression"))
    parser.add_argument("--archive-dir", type=Path,
                        default=Path.home() / "Work/oai-test-evidence")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(
        prefix="regression-", dir=args.output_dir.resolve()))
    validator = Path(__file__).with_name("validate-ric-failback.py")
    summary = {"passed": False, "rounds": []}
    print(f"Regression evidence: {output}", flush=True)
    try:
        for number in range(1, 4):
            print(f"\n=== Proactive RIC failback regression {number}/3 ===",
                  flush=True)
            directory = output / f"round-{number}"
            subprocess.run(
                [sys.executable, str(validator),
                 "--output-dir", str(directory)],
                stdin=subprocess.DEVNULL, check=True)
            files = list(directory.glob("run-*/summary.json"))
            if len(files) != 1:
                raise RuntimeError(f"Round {number}: expected exactly one summary")
            result = json.loads(files[0].read_text(encoding="utf-8"))
            for key in (
                "passed", "proactive_failback",
                "backup_ric_running_and_unchanged",
                "agents_unchanged_throughout",
                "no_return_while_primary_stopped",
                "baseline_restored",
            ):
                if result.get(key) is not True:
                    raise RuntimeError(f"Round {number}: unexpected {key}")
            if (result.get("on-b_kpm_nodes") != [1, 2, 3]
                    or result.get("on-a_kpm_nodes") != [1, 2]
                    or result.get("cleanup_errors")):
                raise RuntimeError(f"Round {number}: KPM or cleanup failure")
            summary["rounds"].append({
                "round": number,
                "passed": True,
                "summary": str(files[0].relative_to(output)),
            })
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (output / "regression-summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {output}", flush=True)

    args.archive_dir.mkdir(parents=True, exist_ok=True)
    archive = args.archive_dir / (
        "flexric-ric-failback-regression-"
        + datetime.now().strftime("%Y%m%d-%H%M%S")
        + "-" + output.name + ".tar.gz"
    )
    subprocess.run(
        ["tar", "-czf", str(archive), "-C", str(output.parent), output.name],
        check=True, timeout=60)
    print("PASS: all three verified proactive failback rounds.", flush=True)
    print(f"Archived: {archive}", flush=True)


if __name__ == "__main__":
    main()
