#!/usr/bin/env python3
"""Run three verified experimental N2 handover rounds and archive evidence."""
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
                        default=Path("/tmp/oai-n2-handover-regression"))
    parser.add_argument("--archive-dir", type=Path,
                        default=Path.home() / "Work/oai-test-evidence")
    parser.add_argument("--xapp-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-ue-context-test")
    parser.add_argument("--compose-overlay", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(
        prefix="regression-", dir=args.output_dir.resolve()))
    validator = Path(__file__).with_name("validate-oai-n2-handover.py")
    summary = {"passed": False, "rounds": []}
    print(f"Regression evidence: {output}", flush=True)
    try:
        for number in range(1, 4):
            print(f"\n=== N2 handover regression {number}/3 ===", flush=True)
            directory = output / f"round-{number}"
            command = [
                sys.executable, str(validator),
                "--output-dir", str(directory),
                "--xapp-image", args.xapp_image,
            ]
            if args.compose_overlay is not None:
                command += ["--compose-overlay",
                            str(args.compose_overlay.resolve(strict=True))]
            subprocess.run(command, stdin=subprocess.DEVNULL, check=True)
            files = list(directory.glob("run-*/summary.json"))
            if len(files) != 1:
                raise RuntimeError(f"Round {number}: expected one summary")
            result = json.loads(files[0].read_text(encoding="utf-8"))
            for key in (
                "passed", "all_four_processes_unchanged",
                "target_handover_complete_and_notify",
                "target_pdu_session_established", "source_ue_removed",
                "ue_ip_unchanged",
            ):
                if result.get(key) is not True:
                    raise RuntimeError(f"Round {number}: failed {key}")
            if (result.get("post_handover_ping_received") != 5
                    or result.get("cleanup_errors")):
                raise RuntimeError(f"Round {number}: traffic or cleanup failure")
            summary["rounds"].append({
                "number": number, "passed": True,
                "evidence": str(files[0].parent.relative_to(output)),
            })
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        args.archive_dir.mkdir(parents=True, exist_ok=True)
        archive = args.archive_dir / (
            "oai-n2-handover-regression-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-" + output.name + ".tar.gz")
        subprocess.run(
            ["tar", "-czf", str(archive), "-C", str(output.parent), output.name],
            check=True, timeout=60)
        print(f"Archived: {archive}", flush=True)
    print("PASS: all three verified N2 handover rounds.", flush=True)

if __name__ == "__main__":
    main()
