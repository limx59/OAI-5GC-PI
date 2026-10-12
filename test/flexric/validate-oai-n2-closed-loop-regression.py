#!/usr/bin/env python3
"""Run three closed-loop rounds in one session, including NCC wrap."""
import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-n2-closed-loop-regression"))
    parser.add_argument("--archive-dir", type=Path,
                        default=Path.home() / "Work/oai-test-evidence")
    parser.add_argument("--inventory-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-cell-inventory-test")
    parser.add_argument("--control-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-n2-bidirectional-test")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="regression-", dir=args.output_dir.resolve()))
    print(f"Regression evidence: {output}", flush=True)
    validator = Path(__file__).with_name("validate-oai-n2-closed-loop.py")
    docker = ["sudo", "docker"]
    names = ["oai-pi-oai-e2-lab-ric-1", "oai-pi-oai-e2-lab-gnb-1",
             "oai-pi-oai-e2-lab-gnb-2-1", "oai-pi-oai-e2-lab-nrue-1"]
    started = datetime.now(timezone.utc).isoformat()
    summary = {"passed": False, "rounds": []}

    def inspect():
        result = subprocess.run(docker + ["inspect", *names],
                                capture_output=True, text=True, check=True, timeout=20)
        records = json.loads(result.stdout)
        if not all(item["State"]["Running"] for item in records):
            raise RuntimeError("A baseline process is stopped")
        return {item["Name"].lstrip("/"): [
            item["Id"], item["Image"], item["State"]["Pid"],
            item["State"]["StartedAt"], item["RestartCount"],
            item["HostConfig"]["CpusetCpus"]] for item in records}

    try:
        initial = inspect()
        for number in range(1, 4):
            print(f"\n=== Actual-MAC closed-loop regression {number}/3 ===", flush=True)
            directory = output / f"round-{number}"
            subprocess.run([
                sys.executable, str(validator), "--output-dir", str(directory),
                "--inventory-image", args.inventory_image,
                "--control-image", args.control_image,
            ], stdin=subprocess.DEVNULL, check=True)
            paths = list(directory.glob("run-*/summary.json"))
            if len(paths) != 1:
                raise RuntimeError("Expected one round summary")
            result = json.loads(paths[0].read_text())
            for key in ("passed", "idle_no_action", "cooldown_observed",
                        "all_four_processes_unchanged", "ue_ip_unchanged"):
                if result.get(key) is not True:
                    raise RuntimeError(f"Round {number}: missing check {key}")
            if result["cleanup_errors"] or result["final_serving_node"] != 3584:
                raise RuntimeError("Round cleanup/topology check failed")
            if inspect() != initial:
                raise RuntimeError("Processes changed across regression rounds")
            summary["rounds"].append({
                "round": number, "evidence": str(paths[0].parent),
                "actions": result["actions"], "bursts": result["bursts"]})
        wrap = False
        for name in names[1:]:
            result = subprocess.run(
                docker + ["logs", "--timestamps", "--since", started, name],
                capture_output=True, text=True, check=True, timeout=30)
            lines = (result.stdout + result.stderr).splitlines()
            selected = [line for line in lines if any(marker in line for marker in (
                "NCC synchronization:", "Received masterKeyUpdate",
                "integrity failed", "handover for UE", "Handover Notify"))]
            (output / f"{name}-regression-events.log").write_text(
                "\n".join(selected) + "\n")
            if any("integrity failed" in line for line in selected):
                raise RuntimeError(f"{name}: integrity failure during regression")
            if name == names[3]:
                counts = [
                    int(match.group(1)) for line in selected
                    if (match := re.search(
                        r"local count=(\d+), received=0, steps=1", line))
                ]
                wrap = any(count >= 7 and count % 8 == 7 for count in counts)
                for line in selected:
                    if "NCC synchronization:" in line:
                        print(line, flush=True)
        if not wrap:
            raise RuntimeError("NCC 7 -> 0 runtime evidence missing")
        summary.update(passed=True, ncc_wrap_verified=True,
                       all_four_processes_unchanged_across_rounds=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        args.archive_dir.mkdir(parents=True, exist_ok=True)
        archive = args.archive_dir / (
            "oai-n2-closed-loop-regression-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-" + output.name + ".tar.gz")
        subprocess.run(["tar", "-czf", str(archive), "-C",
                        str(output.parent), output.name], check=True, timeout=60)
        print(f"Archived: {archive}", flush=True)
    print("PASS: three closed-loop rounds and verified NCC wrap in one session.",
          flush=True)

if __name__ == "__main__":
    main()
