#!/usr/bin/env python3
"""Validate persistent KPM recovery using an existing multi-RIC deployment."""

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
    parser.add_argument("--scenario", choices=("ric-restart",), required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-dockerhub-kpm-recovery"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)

    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    deploy = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
    for filename in ("compose.emulator.yaml", "compose.multi-agent.yaml",
                     "compose.multi-ric.yaml", "compose.kpm-recovery.yaml"):
        compose += ["-f", str(deploy / filename)]
    services = ("ric", "ric-2", "emulator", "emulator-2", "emulator-3")
    token = uuid.uuid4().hex[:10]
    xapps = {f"kpm-recovery-{token}-a": ("xapp-kpm", {1, 2}),
             f"kpm-recovery-{token}-b": ("xapp-kpm-ric2", {3})}
    a, b = xapps
    containers = {}
    created = []
    restore_needed = False
    summary = {"scenario": args.scenario, "result": "FAIL"}
    sequence = 0

    def run(command, label, timeout=30):
        nonlocal sequence
        sequence += 1
        path = output / f"{sequence:03d}-{label}.log"
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decode(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            path.write_text(decode(error.stdout) + decode(error.stderr),
                            encoding="utf-8")
            raise RuntimeError(f"{label}: timeout; inspect {path}") from error
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0, f"{label}: inspect {path}")
        return result.stdout, result.stdout + result.stderr

    def logs(name):
        return run(docker + ["logs", "--timestamps", name], f"logs-{name}")[1]

    def snapshot(label):
        data = json.loads(run(docker + ["inspect", *containers.values()],
                              label)[0])
        states = {s["Id"]: s for s in data}
        return {key: {
            "id": states[value]["Id"],
            "started_at": states[value]["State"]["StartedAt"],
            "restart_count": states[value]["RestartCount"],
            "running": states[value]["State"]["Running"],
            "image_id": states[value]["Image"],
            "configured_image": states[value]["Config"]["Image"],
        } for key, value in containers.items()}

    def counts(text, since):
        result = {}
        for node, stamp in re.findall(
                r"KPM node=(\d+) received_utc=([^\s]+)", text):
            if datetime.fromisoformat(stamp) > since:
                node = int(node)
                result[node] = result.get(node, 0) + 1
        return result

    def wait_ready():
        deadline = time.monotonic() + 30
        while True:
            ready = True
            for name, (_, expected) in xapps.items():
                text = logs(name)
                found = {int(n) for n in re.findall(r"Subscribed: node=(\d+)", text)}
                ready &= ("READY: persistent subscriptions" in text and
                          found == expected and
                          all(counts(text, began).get(n, 0) >= 2 for n in expected))
            if ready:
                return
            require(time.monotonic() < deadline, "Persistent xApps not ready")
            time.sleep(1)

    try:
        run(compose + ["--profile", "tools", "config", "--quiet"], "config")
        for service in services:
            container = run(compose + ["ps", "-q", service],
                            f"id-{service}")[0].strip()
            require(bool(container) and "\n" not in container,
                    f"{service}: expected one running container")
            containers[service] = container
        began = datetime.now(timezone.utc)
        for name, (service, _) in xapps.items():
            created.append(name)
            container = run(compose + [
                "--profile", "tools", "run", "-d", "-T", "--no-deps",
                "--pull", "never", "--name", name, service,
                "xapp_kpm_recovery.py", "-c", "/usr/local/etc/flexric/xapp.conf",
            ], f"start-{name}", timeout=45)[0].strip()
            containers[name] = container
        wait_ready()
        before = snapshot("before")
        require(all(s["running"] for s in before.values()), "Baseline not running")
        print("PASS: both persistent xApps ready and reporting", flush=True)

        restore_needed = True
        run(compose + ["stop", "ric"], "stop-ric-a", timeout=45)
        state = json.loads(run(docker + ["inspect", containers["ric"]],
                              "ric-stopped")[0])[0]
        require(not state["State"]["Running"], "RIC A did not stop")
        outage = datetime.now(timezone.utc)
        time.sleep(5)
        require(counts(logs(b), outage).get(3, 0) >= 2,
                "RIC B reports missing during outage")
        print("PASS: RIC B persistent reports during outage", flush=True)

        restarted = datetime.now(timezone.utc)
        run(compose + ["start", "ric"], "start-ric-a")
        deadline = time.monotonic() + 60
        while True:
            text = logs(a)
            require(not any(m in text for m in ("Assertion", "Traceback")),
                    "Persistent xApp failed during recovery")
            acknowledgements = set(re.findall(
                r"\[KPM recovery\]: replay ACK request=(\d+)", text))
            if acknowledgements == {"1", "2"} and all(
                    counts(text, restarted).get(n, 0) >= 2 for n in (1, 2)):
                break
            require(time.monotonic() < deadline, "Recovery exceeded 60 seconds")
            time.sleep(1)
        require(counts(logs(b), restarted).get(3, 0) >= 2,
                "RIC B reports missing after restart")
        after = snapshot("after")
        for key, old in before.items():
            new = after[key]
            require(new["running"] and old["id"] == new["id"] and
                    old["restart_count"] == new["restart_count"] and
                    old["image_id"] == new["image_id"],
                    f"{key}: unexpected state or identity change")
            require((old["started_at"] != new["started_at"]) if key == "ric"
                    else (old["started_at"] == new["started_at"]),
                    f"{key}: unexpected startup time")
        print("PASS: replay ACKs, resumed reports and unchanged xApp/Agent processes",
              flush=True)

        for name, (_, expected) in xapps.items():
            run(docker + ["exec", name, "python3", "-c",
                         "from pathlib import Path; "
                         "Path('/tmp/kpm-recovery-stop').touch()"],
                f"stop-marker-{name}")
            require(run(docker + ["wait", name], f"wait-{name}")[0].strip() == "0",
                    f"{name}: abnormal exit")
            text = logs(name)
            require("STOP: requested normal subscription cleanup" in text and
                    text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(expected),
                    f"{name}: cleanup incomplete")
            require(not any(m in text for m in
                            ("Assertion", "Traceback", "callback error:")),
                    f"{name}: error detected")
        final = snapshot("final")
        require(all(final[s]["running"] for s in services),
                "Infrastructure stopped during cleanup")
        for service in services:
            require("Assertion" not in logs(containers[service]),
                    f"{service}: assertion detected")
        restore_needed = False
        summary.update(result="PASS", before=before, after=after, final=final)
        print("PASS: persistent subscription recovery and normal cleanup", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        cleanup_errors = []
        if restore_needed:
            try:
                run(compose + ["start", "ric"], "restore-ric-a")
            except Exception as error:
                cleanup_errors.append(str(error))
        for key, container in containers.items():
            for action in ("logs", "inspect"):
                command = docker + [action]
                if action == "logs":
                    command.append("--timestamps")
                try:
                    run(command + [container], f"evidence-{key}-{action}")
                except Exception as error:
                    cleanup_errors.append(str(error))
        for name in created:
            try:
                run(docker + ["rm", "-f", name], f"remove-{name}")
            except Exception as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            summary["cleanup_errors"] = cleanup_errors
            summary["result"] = "FAIL"
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {output}", flush=True)
        require(not cleanup_errors, f"Evidence/cleanup errors: {cleanup_errors}")


if __name__ == "__main__":
    main()
