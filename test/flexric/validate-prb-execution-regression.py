#!/usr/bin/env python3
"""Run three E2-directed NR PRB execution validation rounds and archive evidence."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-e2-prb-regression"))
    parser.add_argument("--archive-dir", type=Path,
                        default=Path.home() / "Work/oai-test-evidence")
    parser.add_argument("--project", default="oai-pi-prb-execution-lab")
    parser.add_argument("--xapp-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-prb-execution-test")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.archive_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(
        prefix="regression-", dir=args.output_dir.resolve()))
    validator = Path(__file__).with_name("validate-prb-execution.py")
    summary = {"passed": False, "rounds": [],
               "project": args.project, "xapp_image": args.xapp_image,
               "scope": "E2-triggered independent real NR DL scheduler simulations"}
    print(f"Regression evidence: {output}", flush=True)
    baseline = None
    try:
        require(validator.is_file(), "Validation script not found")
        for number in range(1, 4):
            print(f"\n=== PRB execution regression {number}/3 ===", flush=True)
            directory = output / f"round-{number}"
            subprocess.run(
                [sys.executable, str(validator),
                 "--output-dir", str(directory),
                 "--project", args.project,
                 "--xapp-image", args.xapp_image],
                stdin=subprocess.DEVNULL, check=True)
            files = list(directory.glob("run-*/summary.json"))
            require(len(files) == 1, f"Round {number}: expected one summary")
            result = json.loads(files[0].read_text(encoding="utf-8"))
            require(result["passed"] is True, f"Round {number}: validation failed")
            require(result["all_four_processes_unchanged"] is True,
                    f"Round {number}: process identity changed")
            require(not result["cleanup_errors"], f"Round {number}: cleanup failed")
            require(len(result["cases"]) == 11
                    and all(c["passed"] is True for c in result["cases"]),
                    f"Round {number}: incomplete checks")
            executions = [c for c in result["cases"] if "execution" in c]
            require(len(executions) == 6
                    and all(c.get("independent_raw_audit") is True
                            for c in executions),
                    f"Round {number}: missing raw-grant audits")
            identities = json.loads(
                (files[0].parent / "before.json").read_text(encoding="utf-8"))
            if baseline is None:
                baseline = identities
            require(identities == baseline,
                    f"Round {number}: processes changed between rounds")
            summary["rounds"].append({
                "round": number, "passed": True,
                "evidence": str(files[0].parent),
                "checks": 11, "verified_scheduler_executions": 6,
            })
        summary["same_processes_across_rounds"] = True
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        archive = args.archive_dir.resolve() / (
            "oai-e2-prb-regression-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-" + output.name + ".tar.gz")
        subprocess.run(
            ["tar", "-czf", str(archive),
             "-C", str(output.parent), output.name],
            check=True, timeout=60)
        print(f"Archived: {archive}", flush=True)
    print("PASS: all three verified PRB execution rounds.", flush=True)

if __name__ == "__main__":
    main()
