#!/usr/bin/env python3
"""Validate fault-driven A -> B -> A failover without Agent recreation."""

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
                        default=Path("/tmp/flexric-ric-failover-bidirectional-auto"))
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
    a = "oai-pi-flexric-lab-ric-1"
    b = "oai-pi-flexric-lab-ric-2-1"
    agents = [
        "oai-pi-flexric-lab-emulator-1",
        "oai-pi-flexric-lab-emulator-2-1",
    ]
    names = [a, b, *agents, "oai-pi-flexric-lab-emulator-3-1"]
    prefix = "bidirectional-" + uuid.uuid4().hex[:10]
    temporary = []
    faulted = False
    completed = False
    before = None
    summary = {
        "passed": False,
        "scope": "Fault-driven A -> B -> A within unchanged Agent 1 and 2 processes",
        "limitations": [
            "This does not implement proactive automatic failback.",
            "Network blackhole scenarios are not tested.",
            "Fresh xApp subscriptions are used; existing subscriptions do not migrate.",
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
        return result.stdout

    def inspect(filename):
        items = json.loads(run(docker + ["inspect", *names], filename))
        return {item["Name"].lstrip("/"): item for item in items}

    def identity(item):
        return (
            item["Id"], item["Image"], item["State"]["Pid"],
            item["State"]["StartedAt"], item["RestartCount"],
        )

    def unchanged_agents(items):
        for name in agents:
            require(items[name]["State"]["Running"], f"{name} stopped")
            require(identity(items[name]) == identity(before[name]),
                    f"{name} process changed")

    def topology(phase):
        run([
            "python3", str(root / "test/flexric/validate-topology.py"),
            "--scenario", "multi-ric", "--checks", "nodes", "kpm",
            "--output-dir", str(output / phase),
        ], phase + "-command.log", timeout=120)

    def wait_ric(name, phase):
        deadline = time.monotonic() + 20
        while True:
            items = inspect(phase + "-inspect.json")
            require(items[name]["State"]["Running"], f"{name} is not running")
            try:
                run(docker + ["exec", name, "python3", "-c",
                    "from pathlib import Path; rows=Path('/proc/net/sctp/eps').read_text().splitlines()[1:]; assert any('36421' in row.split() for row in rows), 'RIC SCTP listener not ready'"],
                    phase + "-probe.log")
                return items
            except RuntimeError:
                require(time.monotonic() < deadline, f"{name} readiness timeout")
                time.sleep(0.5)

    def wait_switch(phase, since, direction, destination):
        deadline = time.monotonic() + 25
        while True:
            ready = True
            for name in agents:
                run(docker + ["logs", "--timestamps", "--since", since, name],
                    f"{phase}-{name}.log")
                text = (output / f"{phase}-{name}.log").read_text(encoding="utf-8")
                require(not any(marker in text for marker in (
                    "Assertion", "subscription cleanup failed",
                )), f"{name} failover error")
                ready &= direction in text and "E2 SETUP RESPONSE rx" in text
            if ready:
                items = inspect(phase + "-inspect.json")
                unchanged_agents(items)
                require(items[destination]["State"]["Running"],
                        "Destination RIC stopped")
                return items
            require(time.monotonic() < deadline, f"{phase} switch timeout")
            time.sleep(0.5)

    def kpm(service, expected, phase):
        name = prefix + "-" + phase
        temporary.append(name)
        run(compose + [
            "--profile", "tools", "run", "-T", "--rm",
            "--no-deps", "--pull", "never", "--name", name, service,
        ], phase + "-kpm.log", timeout=45)
        text = (output / (phase + "-kpm.log")).read_text(encoding="utf-8")
        require(not any(marker in text for marker in (
            "Traceback", "Assertion", "callback error:", "DirectorMethodException",
        )), f"{phase} KPM error")
        nodes = {int(v) for v in re.findall(
            r"^KPM node=(\d+)", text, re.MULTILINE)}
        require(nodes == expected, f"{phase} KPM nodes: {nodes}")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(expected),
                f"{phase} subscription cleanup incomplete")
        unchanged_agents(inspect(phase + "-post-kpm-inspect.json"))
        summary[phase + "_kpm_nodes"] = sorted(nodes)
        print(f"PASS: {phase} KPM nodes={sorted(nodes)} and subscription cleanup",
              flush=True)

    try:
        topology("baseline")
        before = inspect("before-inspect.json")
        require(all(item["State"]["Running"] for item in before.values()),
                "Baseline containers must all be running")

        since = datetime.now(timezone.utc).isoformat()
        summary["fault_a_requested_at"] = since
        faulted = True
        run(docker + ["kill", "--signal", "KILL", a], "kill-a.log")
        items = wait_switch("a-to-b", since,
                            "switching 172.29.0.10 -> 172.29.0.11", b)
        require(not items[a]["State"]["Running"]
                and items[a]["State"]["ExitCode"] == 137, "Unexpected RIC A exit")
        require(identity(items[b]) == identity(before[b]), "RIC B process changed")
        kpm("xapp-kpm-ric2", {1, 2, 3}, "on-b")

        run(compose + [
            "up", "-d", "--no-build", "--pull", "never", "--no-deps", "ric",
        ], "restart-a.log", timeout=45)
        restored_a = wait_ric(a, "restored-a")
        unchanged_agents(restored_a)

        since = datetime.now(timezone.utc).isoformat()
        summary["fault_b_requested_at"] = since
        run(docker + ["kill", "--signal", "KILL", b], "kill-b.log")
        items = wait_switch("b-to-a", since,
                            "switching 172.29.0.11 -> 172.29.0.10", a)
        require(not items[b]["State"]["Running"]
                and items[b]["State"]["ExitCode"] == 137, "Unexpected RIC B exit")
        require(identity(items[a]) == identity(restored_a[a]), "RIC A process changed")
        kpm("xapp-kpm", {1, 2}, "on-a")
        completed = True
        summary["same_process_bidirectional_failover"] = True
        print("PASS: A -> B -> A; Agent 1 and 2 processes unchanged",
              flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        errors = []
        for name in temporary:
            try:
                ids = run(docker + [
                    "ps", "-aq", "--filter", "name=^/" + name + "$",
                ]).strip()
                if ids:
                    run(docker + ["logs", "--timestamps", name],
                        name + "-final.log")
                    run(docker + ["rm", "-f", name], name + "-remove.log")
            except Exception as error:
                errors.append(str(error))
        if faulted:
            try:
                run(compose + [
                    "up", "-d", "--no-build", "--pull", "never", "--no-deps",
                    "ric", "ric-2",
                ], "restore-rics.log", timeout=45)
                topology("restored")
                final = inspect("final-inspect.json")
                unchanged_agents(final)
                summary["baseline_restored"] = True
                print("PASS: baseline restored without Agent recreation",
                      flush=True)
            except Exception as error:
                errors.append(str(error))
        summary["passed"] = completed and not errors
        if errors:
            summary["cleanup_errors"] = errors
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {output}", flush=True)
        if errors:
            raise RuntimeError(f"Cleanup/restoration errors: {errors}")


if __name__ == "__main__":
    main()
