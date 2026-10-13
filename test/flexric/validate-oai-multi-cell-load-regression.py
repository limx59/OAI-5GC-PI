#!/usr/bin/env python3
"""Run three concurrent dual-cell RFsim load validations and archive evidence."""
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
                        default=Path("/tmp/oai-multi-cell-load-regression"))
    parser.add_argument("--archive-dir", type=Path,
                        default=Path.home() / "Work/oai-test-evidence")
    parser.add_argument("--xapp-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-mac-100ms-test")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.archive_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="regression-",
                                  dir=args.output_dir.resolve()))
    validator = Path(__file__).with_name("validate-oai-multi-cell-load.py")
    summary = {"passed": False, "rounds": [], "xapp_image": args.xapp_image,
               "scope": "Independent dual-cell RFsim UL/DL and actual MAC rates"}
    baseline = None
    addresses = None
    print(f"Regression evidence: {output}", flush=True)
    try:
        for number in range(1, 4):
            print(f"\n=== Dual-cell load regression {number}/3 ===", flush=True)
            directory = output / f"round-{number}"
            subprocess.run(
                [sys.executable, str(validator),
                 "--xapp-image", args.xapp_image,
                 "--output-dir", str(directory)],
                stdin=subprocess.DEVNULL, check=True, timeout=360)
            files = list(directory.glob("run-*/summary.json"))
            require(len(files) == 1, "Expected one validation summary")
            result = json.loads(files[0].read_text())
            require(result["passed"] and not result["cleanup_errors"],
                    "Validation or cleanup failed")
            require(result["all_five_processes_unchanged"]
                    and result["ue_ips_unchanged"], "Process or IP changed")
            require([phase["label"] for phase in result["phases"]] == [
                "ul-a-high", "ul-b-high", "dl-a-high", "dl-b-high"],
                "Unexpected validation phases")
            require(all(phase["passed"] for phase in result["phases"]),
                    "A validation phase failed")
            if baseline is None:
                baseline = result["before"]
                addresses = result["ue_addresses"]
            require(result["before"] == baseline,
                    "Processes changed between rounds")
            require(result["ue_addresses"] == addresses,
                    "UE addresses changed between rounds")
            summary["rounds"].append({
                "round": number, "passed": True,
                "evidence": str(files[0].parent),
                "phases": 4,
            })
        summary["same_five_processes_across_rounds"] = True
        summary["same_ue_ips_across_rounds"] = True
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        archive = args.archive_dir.resolve() / (
            "oai-multi-cell-load-regression-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-" + output.name + ".tar.gz")
        subprocess.run(
            ["tar", "-czf", str(archive), "-C", str(output.parent), output.name],
            check=True, timeout=60)
        print(f"Archived: {archive}", flush=True)
    print("PASS: three dual-cell UL/DL load rounds with unchanged processes/IPs.",
          flush=True)

if __name__ == "__main__":
    main()
