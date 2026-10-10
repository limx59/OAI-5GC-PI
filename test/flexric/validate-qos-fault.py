#!/usr/bin/env python3
"""Validate QoS report silence and recovery by pausing Agent 2."""

import argparse
from collections import Counter
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
    parser.add_argument("--scenario", choices=("agent-pause",), required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-qos-fault"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)
    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    deploy = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
    for filename in ("compose.emulator.yaml", "compose.multi-agent.yaml",
                     "compose.multi-ric.yaml", "compose.kpm-recovery.yaml",
                     "compose.qos-fault.yaml"):
        compose += ["-f", str(deploy / filename)]
    metrics = ("DRB.UEThpDl", "DRB.UEThpUl")
    pairs = {(node, metric) for node in (1, 2, 3) for metric in metrics}
    target = {(2, metric) for metric in metrics}
    token = uuid.uuid4().hex[:10]
    a, b = f"qos-fault-{token}-a", f"qos-fault-{token}-b"
    services = ("ric", "ric-2", "emulator", "emulator-2", "emulator-3")
    containers = {}
    created = []
    paused = False
    result_status = "FAIL"
    cleanup_errors = []

    def run(command, label, timeout=30):
        path = output / f"{label}.log"
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decode(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            path.write_text(decode(error.stdout) + decode(error.stderr),
                            encoding="utf-8")
            raise RuntimeError(f"{label}: timeout; inspect {path}") from error
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0, f"{label}: inspect {path}")
        return result.stdout

    def logs(name, label):
        run(docker + ["logs", "--timestamps", name], label)
        return (output / f"{label}.log").read_text(encoding="utf-8")

    def snapshot(label):
        states = json.loads(run(
            docker + ["inspect", *containers.values(), *created], label))
        return {state["Id"]: state for state in states}

    def events(text, label):
        return Counter((int(node), metric) for node, metric in re.findall(
            rf"\b{label}: node=(\d+) metric=(DRB\.UEThp(?:Dl|Ul))", text))

    def reports_after(text, since):
        return Counter((int(node), metric) for node, metric, stamp in re.findall(
            r"\bREPORT: node=(\d+) metric=(DRB\.UEThp(?:Dl|Ul)) "
            r"received_utc=(\S+)", text)
            if datetime.fromisoformat(stamp) >= since)

    def clean_text(text):
        require(not any(marker in text for marker in
                        ("Assertion", "Traceback", "error:",
                         "Skipping mismatched", "Unsupported")),
                "Error found in xApp logs")

    def wait_for(check, label, timeout=25):
        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            attempt += 1
            texts = [logs(name, f"{label}-{attempt}-{name}") for name in (a, b)]
            for text in texts:
                clean_text(text)
            if check(texts):
                return texts
            require(time.monotonic() < deadline, f"{label}: timed out")
            time.sleep(0.5)

    try:
        run(compose + ["--profile", "tools", "config", "--quiet"], "config")
        for service in services:
            container = run(compose + ["ps", "-q", service],
                            f"{service}-id").strip()
            require(bool(container), f"{service}: running container missing")
            containers[service] = container

        for name, service in ((a, "xapp-kpm"), (b, "xapp-kpm-ric2")):
            created.append(name)
            run(compose + [
                "--profile", "tools", "run", "-d", "-T", "--no-deps",
                "--pull", "never", "--name", name,
                "-e", "XAPP_QOS_THRESHOLD=1000000000",
                "-e", "XAPP_QOS_LOW_REPORTS=2",
                "-e", "XAPP_QOS_REPORT_TIMEOUT=5",
                service, "xapp_qos_fault_watch.py",
                "-c", "/usr/local/etc/flexric/xapp.conf",
            ], f"start-{name}", timeout=45)

        texts = wait_for(
            lambda texts: all("READY:" in t for t in texts)
            and events("".join(texts), "ALERT") == Counter(dict.fromkeys(pairs, 1)),
            "baseline")
        require(not events("".join(texts), "STALE"), "Baseline already stale")
        before = snapshot("before")
        require(all(s["State"]["Running"] and not s["State"]["Paused"]
                    for s in before.values()), "Baseline container not running")
        print("PASS: initial QoS alerts for all nodes and metrics", flush=True)

        pause_time = datetime.now(timezone.utc)
        paused = True
        run(docker + ["pause", containers["emulator-2"]], "pause-agent-2")
        time.sleep(8)
        texts = [logs(name, f"paused-{name}") for name in (a, b)]
        combined = "".join(texts)
        clean_text(combined)
        require(events(combined, "STALE") == Counter(dict.fromkeys(target, 1)),
                "Timeout must affect only node 2, once per metric")
        counts = reports_after(combined, pause_time)
        require(all(counts[pair] >= 3 for pair in pairs - target),
                "Control nodes did not keep reporting during pause")
        require(events(combined, "ALERT") == Counter(dict.fromkeys(pairs, 1)),
                "Unexpected alert reset during pause")
        print("PASS: only node 2 stale; nodes 1 and 3 continue reporting", flush=True)

        resume_time = datetime.now(timezone.utc)
        run(docker + ["unpause", containers["emulator-2"]], "unpause-agent-2")
        paused = False
        expected_alerts = Counter(dict.fromkeys(pairs, 1))
        expected_alerts.update(target)

        def recovered(texts):
            combined = "".join(texts)
            return (
                events(combined, "REPORT_RECOVERY") ==
                Counter(dict.fromkeys(target, 1))
                and events(combined, "ALERT") == expected_alerts
                and all(reports_after(combined, resume_time)[pair] >= 3
                        for pair in pairs)
            )

        texts = wait_for(recovered, "recovered")
        require(events("".join(texts), "STALE") ==
                Counter(dict.fromkeys(target, 1)), "Unexpected extra timeout")
        after = snapshot("recovered-identities")
        require(before.keys() == after.keys(), "Container identities changed")
        for identity, old in before.items():
            current = after[identity]
            require(current["State"]["Running"] and not current["State"]["Paused"],
                    f"{current['Name']}: not running")
            require(old["State"]["StartedAt"] == current["State"]["StartedAt"]
                    and old["RestartCount"] == current["RestartCount"],
                    f"{current['Name']}: restarted")
        print("PASS: report recovery, alert rearming and unchanged processes",
              flush=True)

        for name in (a, b):
            run(docker + ["exec", name, "python3", "-c",
                          "from pathlib import Path; "
                          "Path('/tmp/qos-fault-stop').touch()"],
                f"stop-{name}")
        for name, expected in ((a, 2), (b, 1)):
            require(run(docker + ["wait", name], f"wait-{name}").strip() == "0",
                    f"{name}: abnormal exit")
            text = logs(name, f"final-{name}")
            clean_text(text)
            require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == expected,
                    f"{name}: incomplete subscription deletion")
        final = snapshot("after-cleanup")
        for identity, state in final.items():
            if identity in {containers[service] for service in services}:
                require(state["State"]["Running"], "Lab container exited")
        result_status = "PASS"
        print("PASS: normal subscription cleanup; lab remains running", flush=True)
    finally:
        if paused:
            try:
                run(docker + ["unpause", containers["emulator-2"]],
                    "emergency-unpause")
            except Exception as error:
                cleanup_errors.append(str(error))
        for name in [*containers.values(), *created]:
            for action in ("logs", "inspect"):
                try:
                    command = docker + [action]
                    if action == "logs":
                        command.append("--timestamps")
                    run(command + [name], f"evidence-{name}-{action}")
                except Exception as error:
                    cleanup_errors.append(str(error))
        for name in created:
            try:
                run(docker + ["rm", "-f", name], f"remove-{name}")
            except Exception as error:
                cleanup_errors.append(str(error))
        (output / "summary.json").write_text(json.dumps({
            "scenario": args.scenario, "result": result_status,
            "scope": "Eight-second Agent 2 pause, report recovery and QoS alert rearming",
            "cleanup_errors": cleanup_errors,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {output}", flush=True)
        if cleanup_errors:
            raise RuntimeError(f"Evidence/cleanup errors: {cleanup_errors}")


if __name__ == "__main__":
    main()
