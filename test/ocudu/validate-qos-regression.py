#!/usr/bin/env python3
"""Repeat the QoS monitor and managed-session recovery tests serially."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

from qos_startup_guard import wait_host_ready


def utc():
    return datetime.now(timezone.utc).isoformat()


def failure_logs(dest, started, finished):
    important = re.compile(
        r"error|warning|heartbeat|NF registered|NF_DEREGISTERED", re.I,
    )
    sensitive = re.compile(
        r"authentication|vector|\b(key|opc|kamf|kseaf|kausf|rand|autn|xres)\b",
        re.I,
    )
    errors = []
    for name in ("amf", "ausf", "udm", "udr", "scp", "nrf"):
        try:
            result = subprocess.run(
                ["sudo", "docker", "logs", "--timestamps",
                 "--since", started, "--until", finished, name],
                capture_output=True, text=True, timeout=20,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode:
                errors.append(f"{name}: log command exit {result.returncode}")
                continue
            lines = []
            for line in (result.stdout + result.stderr).splitlines():
                if not important.search(line) or sensitive.search(line):
                    continue
                line = re.sub(r"suci-[0-9-]+", "<redacted-suci>", line)
                line = re.sub(r"\d{14,16}", "<redacted-identity>", line)
                lines.append(line)
            (dest / f"core-{name}-errors.log").write_text(
                "\n".join(lines) + "\n"
            )
        except Exception as error:
            errors.append(f"{name}: {error}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=3)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    cases = ("validate-qos-monitor.py", "validate-qos-recovery.py")
    sources = (
        "qos_monitor_state.py", "qos_recovery_stream.py",
        "qos_startup_guard.py", "test-qos-startup-guard.py",
        "test-qos-monitor-state.py", "xapp-qos-monitor.py", *cases,
    )
    if not shutil.which("vmstat"):
        raise SystemExit("STOP: vmstat is unavailable")
    for name in sources:
        compile((root / name).read_text(), str(root / name), "exec")

    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-qos-regression-", dir=parent))
    snapshots = dest / "source"
    snapshots.mkdir()
    hashes = {}
    for name in sources:
        data = (root / name).read_bytes()
        (snapshots / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()

    summary = {
        "passed": False, "started_utc": utc(),
        "requested_rounds": args.rounds,
        "source_sha256": hashes, "runs": [],
        "automatic_core_restart": False,
    }

    def save():
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )

    print(f"Regression evidence: {dest}", flush=True)
    save()
    env = {
        **os.environ, "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1", "LC_ALL": "C", "TZ": "UTC",
    }
    try:
        for number in range(1, args.rounds + 1):
            for case in cases:
                for name, expected in hashes.items():
                    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
                    if actual != expected:
                        raise RuntimeError(f"Source changed during regression: {name}")

                run = dest / f"round-{number}-{Path(case).stem}"
                run.mkdir()
                item = {
                    "round": number, "case": case,
                    "started_utc": utc(), "passed": False,
                }
                summary["runs"].append(item)
                save()
                print(f"\n=== Round {number}/{args.rounds}: {case} ===",
                      flush=True)
                item["stage"] = "host_readiness"
                save()
                readiness = wait_host_ready(run / "host-readiness.json")
                item["host_readiness_passed"] = readiness["passed"]
                item["stage"] = "validator"
                save()
                process = None
                with (run / "vmstat.log").open("w") as resources:
                    monitor = subprocess.Popen(
                        ["vmstat", "-w", "-t", "1"],
                        stdin=subprocess.DEVNULL,
                        stdout=resources, stderr=subprocess.STDOUT, env=env,
                    )
                    try:
                        with (run / "validator.log").open("w") as output:
                            process = subprocess.Popen(
                                [sys.executable, "-B", "-u", str(root / case)],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, bufsize=1, env=env,
                            )
                            for line in process.stdout:
                                output.write(line)
                                output.flush()
                                print(line, end="", flush=True)
                                if line.startswith("Evidence: "):
                                    item["case_evidence"] = line.split(
                                        "Evidence: ", 1
                                    )[1].strip()
                            item["exit_code"] = process.wait()
                    finally:
                        if process is not None and process.poll() is None:
                            process.send_signal(signal.SIGINT)
                            try:
                                process.wait(timeout=180)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                        monitor.terminate()
                        try:
                            monitor.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            monitor.kill()
                            monitor.wait()

                item["finished_utc"] = utc()
                if item["exit_code"] == 0:
                    evidence = item.get("case_evidence")
                    if not evidence:
                        raise RuntimeError("Validator did not report its evidence path")
                    result = json.loads(
                        (Path(evidence) / "summary.json").read_text()
                    )
                    item["passed"] = (
                        result.get("passed") is True
                        and result.get("cleanup_errors") == []
                    )
                if not item["passed"]:
                    item["diagnostic_errors"] = failure_logs(
                        run, item["started_utc"], item["finished_utc"],
                    )
                    save()
                    raise RuntimeError(
                        f"Stopped at round {number}: {case}; no automatic retry"
                    )
                save()
        summary["passed"] = True
    except KeyboardInterrupt:
        summary["error"] = "Interrupted by user"
    except Exception as error:
        summary["error"] = str(error)
    finally:
        summary["finished_utc"] = utc()
        save()
        print(f"\nRegression evidence retained: {dest}", flush=True)
        print(json.dumps(summary, indent=2), flush=True)

    if not summary["passed"]:
        raise SystemExit(1)
    print(f"PASS: {args.rounds} rounds; both QoS cases passed in every round.")


if __name__ == "__main__":
    main()
