#!/usr/bin/env python3
"""Validate native Emulator failover; inject SIGKILL and restore the lab."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-ric-failover"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)
    root = Path(__file__).resolve().parents[2]
    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    for filename in (
        "compose.emulator.yaml", "compose.multi-agent.yaml",
        "compose.multi-ric.yaml", "compose.ric-failover.yaml",
    ):
        compose += ["-f", str(root / "deploy/oai-flexric" / filename)]
    primary = "oai-pi-flexric-lab-ric-1"
    stable = [
        "oai-pi-flexric-lab-ric-2-1",
        "oai-pi-flexric-lab-emulator-1",
        "oai-pi-flexric-lab-emulator-2-1",
        "oai-pi-flexric-lab-emulator-3-1",
    ]
    xapp = "ric-failover-active-" + uuid.uuid4().hex[:10]
    created = False
    faulted = False
    summary = {
        "passed": False,
        "scope": "Native Emulator failover with fresh backup KPM subscriptions",
        "limitations": [
            "Existing xApp subscriptions do not migrate.",
            "Old xApp is explicitly stopped after primary RIC failure.",
            "Network blackhole and automatic failback are unvalidated.",
            "Restoration explicitly recreates Agents 1 and 2.",
        ],
    }

    def run(command, filename=None, timeout=30):
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if filename:
                def decode(value):
                    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
                (output / filename).write_text(
                    decode(error.stdout) + decode(error.stderr), encoding="utf-8")
            raise
        if filename:
            (output / filename).write_text(
                result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0,
                f"Command failed ({result.returncode}): {' '.join(command)}")
        return result.stdout + result.stderr

    def inspect(names, filename):
        result = run(docker + ["inspect", *names], filename)
        return {
            item["Name"].lstrip("/"): item
            for item in json.loads(result)
        }

    def identity(item):
        return (
            item["Id"], item["State"]["Pid"], item["State"]["StartedAt"],
            item["RestartCount"], item["Image"],
        )

    def check_stable(before, after):
        for name in stable:
            require(after[name]["State"]["Running"], f"{name} stopped")
            require(identity(before[name]) == identity(after[name]),
                    f"{name} process or image changed")

    try:
        run([
            "python3", str(root / "test/flexric/validate-topology.py"),
            "--scenario", "multi-ric", "--checks", "nodes", "kpm",
            "--output-dir", str(output / "baseline"),
        ], "baseline-command.log", timeout=120)
        print("PASS: primary nodes=[1, 2], backup nodes=[3], baseline KPM",
              flush=True)

        source = root / "test/xapp/xapp_kpm_recovery.py"
        created = True
        run(compose + [
            "--profile", "tools", "run", "-d", "-T",
            "--no-deps", "--pull", "never", "--name", xapp,
            "-v", f"{source}:/opt/oai-pi/test/xapp/xapp_kpm_recovery.py:ro",
            "xapp-kpm", "xapp_kpm_recovery.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ], "active-start.log", timeout=45)

        deadline = time.monotonic() + 25
        while True:
            text = run(docker + ["logs", xapp], "active-before.log")
            require(not any(marker in text for marker in (
                "Traceback", "Assertion", "callback error:",
            )), "Active xApp error")
            nodes = {int(v) for v in re.findall(
                r"^KPM node=(\d+)", text, re.MULTILINE)}
            if nodes == {1, 2} and "READY: persistent subscriptions" in text:
                break
            require(time.monotonic() < deadline, "Active subscriptions not ready")
            time.sleep(0.5)

        names = [primary, *stable, xapp]
        before = inspect(names, "before-inspect.json")
        require(all(item["State"]["Running"] for item in before.values()),
                "A baseline container is not running")
        since = datetime.now(timezone.utc).isoformat()
        summary["fault_requested_at"] = since
        faulted = True
        run(docker + ["kill", "--signal", "KILL", primary], "fault-command.log")

        deadline = time.monotonic() + 25
        while True:
            switched = True
            for name in stable[1:3]:
                text = run(docker + [
                    "logs", "--timestamps", "--since", since, name,
                ], f"{name}-fault.log")
                require(not any(marker in text for marker in (
                    "Assertion", "subscription cleanup failed",
                )), f"{name} failover error")
                switched &= (
                    "switching 172.29.0.10 -> 172.29.0.11" in text
                    and "E2 SETUP RESPONSE rx" in text
                )
            if switched:
                break
            require(time.monotonic() < deadline, "Failover timed out")
            time.sleep(0.5)

        after = inspect(names, "after-inspect.json")
        require(not after[primary]["State"]["Running"]
                and after[primary]["State"]["ExitCode"] == 137,
                "Primary did not exit from SIGKILL")
        check_stable(before, after)
        print("PASS: Agents switched without restart; backup processes unchanged",
              flush=True)

        text = run(compose + [
            "--profile", "tools", "run", "-T", "--rm",
            "--no-deps", "--pull", "never",
            "--name", xapp + "-backup", "xapp-kpm-ric2",
        ], "backup-kpm.log", timeout=45)
        require(not any(marker in text for marker in (
            "Traceback", "Assertion", "callback error:", "DirectorMethodException",
        )), "Backup xApp error")
        nodes = {int(v) for v in re.findall(
            r"^KPM node=(\d+)", text, re.MULTILINE)}
        require(nodes == {1, 2, 3}, f"Unexpected backup KPM nodes: {nodes}")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 3,
                "Expected three subscription deletions")
        check_stable(before, inspect(names, "post-kpm-inspect.json"))
        summary["backup_kpm_nodes"] = sorted(nodes)
        summary["backup_subscription_deletions"] = 3
        summary["passed"] = True
        print("PASS: fresh backup KPM and three subscription deletions", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        errors = []
        if created:
            for command, filename in (
                (docker + ["logs", "--timestamps", xapp], "old-xapp-final.log"),
                (docker + ["stop", "--timeout", "10", xapp], "old-xapp-stop.log"),
                (docker + ["rm", xapp], "old-xapp-remove.log"),
            ):
                try:
                    run(command, filename)
                except Exception as error:
                    errors.append(str(error))
        # Remove a backup xApp left running if its command timed out.
        try:
            leftovers = run(docker + [
                "ps", "-aq", "--filter", "name=^/" + xapp + "-backup$",
            ]).strip()
            if leftovers:
                run(docker + ["rm", "-f", xapp + "-backup"],
                    "backup-forced-cleanup.log")
        except Exception as error:
            errors.append(str(error))
        if faulted:
            try:
                run(compose + [
                    "up", "-d", "--no-build", "--pull", "never", "--no-deps", "ric",
                ], "restore-primary.log", timeout=45)
                run(compose + [
                    "up", "-d", "--no-build", "--pull", "never", "--no-deps",
                    "--force-recreate", "emulator", "emulator-2",
                ], "restore-agents.log", timeout=45)
                run([
                    "python3", str(root / "test/flexric/validate-topology.py"),
                    "--scenario", "multi-ric", "--checks", "nodes", "kpm",
                    "--output-dir", str(output / "restored"),
                ], "restore-validation.log", timeout=120)
                summary["baseline_restored"] = True
                print("PASS: initial topology restored and KPM rechecked",
                      flush=True)
            except Exception as error:
                errors.append(str(error))
        if errors:
            summary["passed"] = False
            summary["cleanup_errors"] = errors
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {output}", flush=True)
        if errors:
            raise RuntimeError(f"Cleanup/restoration errors: {errors}")


if __name__ == "__main__":
    main()
