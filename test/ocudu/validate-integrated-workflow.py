#!/usr/bin/env python3
"""Run the documented OCUDU software-radio regression workflow."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "test/ocudu"
NETWORK = "docker_open5gs_default"
BASE_RIC = "oai-pi-ocudu-zmq-lab-ric-1"
RIC_IMAGE = "limx59/oai-pi-ocudu-flexric-ric:arm64-e2ap3-kpm3-disconnect-fix"
TEST_ADDRESSES = {"172.22.0.151", "172.22.0.160", "172.22.0.161", "172.22.0.163"}

STAGES = (
    ("testmode", "validate-testmode-state-compose.py"),
    ("mac-cell-executor", "validate-mac-cell-executor-fix.py"),
    ("kpm-full-chain", "validate-kpm-csv-ue-identity.py"),
    ("kpm-disconnect", "validate-zmq-kpm-disconnect.py"),
    ("kpm-subscription-rejection", "validate-kpm-subscription-rejection.py"),
    ("kpm-delete-rejection", "validate-kpm-delete-rejection.py"),
)


def docker_json(*args):
    return json.loads(subprocess.check_output(
        ["sudo", "-n", "docker", *args], text=True, timeout=15,
    ))


def network_snapshot():
    network = docker_json("network", "inspect", NETWORK)[0]
    endpoints = {
        cid: item["IPv4Address"].split("/")[0]
        for cid, item in (network.get("Containers") or {}).items()
        if item.get("IPv4Address")
    }
    if not endpoints:
        raise RuntimeError(f"No IPv4 endpoints on {NETWORK}")

    snapshot = {}
    for container in docker_json("inspect", *endpoints):
        state = container["State"]
        if not state["Running"]:
            continue
        snapshot[container["Name"].lstrip("/")] = {
            "id": container["Id"],
            "image": container["Config"]["Image"],
            "pid": state["Pid"],
            "started": state["StartedAt"],
            "restarts": container["RestartCount"],
            "ip": endpoints[container["Id"]],
        }
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    for _, filename in STAGES:
        if not (TESTS / filename).is_file():
            raise RuntimeError(f"Missing test entry point: {filename}")

    baseline = network_snapshot()
    ric = baseline.get(BASE_RIC, {})
    if ric.get("image") != RIC_IMAGE or ric.get("ip") != "172.22.0.162":
        raise RuntimeError("Baseline RIC image or address does not match")
    occupied = TEST_ADDRESSES.intersection(item["ip"] for item in baseline.values())
    if occupied:
        raise RuntimeError(f"Test addresses already occupied: {sorted(occupied)}")

    checker_image = "limx59/oai-pi-ocudu-testmode-state:arm64-config-state-test"
    docker_json("image", "inspect", checker_image)
    print("PASS: workflow entry points, baseline RIC, test addresses and checker image")
    if args.check_only:
        return 0

    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="ocudu-integrated-workflow-", dir=parent))
    summary = output / "summary.json"
    report = {
        "started": datetime.now().astimezone().isoformat(),
        "passed": False,
        "stages": [],
        "baseline": baseline,
    }
    print(f"Workflow evidence: {output}", flush=True)

    try:
        for label, filename in STAGES:
            command = [sys.executable, "-B", str(TESTS / filename)]
            if label == "kpm-disconnect":
                command.extend([
                    "--ric-image", RIC_IMAGE, "--rounds", "1",
                    "--output-dir", str(output / "disconnect"),
                ])

            log = output / f"{label}.log"
            stage = {"name": label, "log": log.name, "evidence_lines": []}
            report["stages"].append(stage)
            print(f"\n=== {label} ===", flush=True)
            with log.open("x", encoding="utf-8") as stream, subprocess.Popen(
                command, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace",
            ) as process:
                for line in process.stdout:
                    stream.write(line)
                    stream.flush()
                    print(line, end="", flush=True)
                    if line.startswith(("Evidence:", "Evidence retained:")):
                        stage["evidence_lines"].append(line.strip())
                stage["exit_code"] = process.wait()

            after = network_snapshot()
            changed = [
                name for name in sorted(baseline.keys() | after.keys())
                if baseline.get(name) != after.get(name)
            ]
            stage["changed_network_containers"] = changed
            if stage["exit_code"] or changed:
                raise RuntimeError(
                    f"{label} failed: exit={stage['exit_code']}, "
                    f"changed network containers={changed}"
                )

        report["passed"] = True
        print("PASS: OCUDU integrated workflow regression", flush=True)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    finally:
        summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Workflow summary: {summary}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
