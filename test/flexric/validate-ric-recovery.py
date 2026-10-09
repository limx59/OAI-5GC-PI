#!/usr/bin/env python3
"""Validate graceful RIC restart and explicit cross-RIC Agent migration."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

DEPLOY = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
SERVICES = ("ric", "ric-2", "emulator", "emulator-2", "emulator-3")
GROUPS = (
    ("a", {1, 2}, "xapp-nodes", "xapp-kpm"),
    ("b", {3}, "xapp-nodes-ric2", "xapp-kpm-ric2"),
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("ric-restart", "ric-migration"), required=True)
    parser.add_argument("--discovery-timeout", type=int, default=90)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-ric-recovery"))
    args = parser.parse_args()
    if args.discovery_timeout < 1:
        parser.error("--discovery-timeout must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="ric-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)

    docker = ["sudo", "docker"]
    compose = [
        "sudo", "env",
        "FLEXRIC_RIC_IMAGE=limx59/flexric-ric:arm64-multi-agent",
        "FLEXRIC_EMULATOR_IMAGE=limx59/flexric-emulator:arm64-multi-agent",
        "FLEXRIC_XAPP_IMAGE=limx59/flexric-xapp:arm64-multi-agent",
        "docker", "compose",
    ]
    for filename in ("compose.emulator.yaml", "compose.multi-agent.yaml",
                     "compose.multi-ric.yaml"):
        compose += ["-f", str(DEPLOY / filename)]

    def run(command, label, timeout=45):
        path = output / f"{label}.log"
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decode(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            path.write_text(
                decode(error.stdout) + decode(error.stderr), encoding="utf-8")
            raise RuntimeError(f"{label}: timeout; inspect {path}") from error
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0,
                f"{label}: exit={result.returncode}; inspect {path}")
        return result.stdout + result.stderr

    def snapshot(label):
        states = {}
        for service in SERVICES:
            container = run(compose + ["ps", "-q", service],
                            f"{label}-{service}-id").strip()
            require(bool(container), f"{service}: running container missing")
            state = json.loads(run(
                docker + ["inspect", container],
                f"{label}-{service}-inspect"))[0]
            require(state["State"]["Running"], f"{service}: not running")
            states[service] = {
                "id": state["Id"],
                "started_at": state["State"]["StartedAt"],
                "restart_count": state["RestartCount"],
                "image_id": state["Image"],
                "configured_image": state["Config"]["Image"],
            }
        (output / f"{label}-identities.json").write_text(
            json.dumps(states, indent=2) + "\n", encoding="utf-8")
        return states

    def xapp(service, label):
        name = f"ric-recovery-{uuid.uuid4().hex[:12]}"
        try:
            return run(
                compose + ["--profile", "tools", "run", "-T", "--rm",
                           "--no-deps", "--pull", "never",
                           "--name", name, service], label, timeout=45)
        finally:
            result = subprocess.run(
                docker + ["rm", "-f", name], capture_output=True,
                text=True, stdin=subprocess.DEVNULL, timeout=20)
            # --rm normally already removed the container.
            require(result.returncode == 0 or
                    "No such container" in result.stderr,
                    f"Temporary xApp cleanup failed: {name}")

    def nodes(group, label, retry=False):
        ric, expected, service, _ = group
        deadline = time.monotonic() + args.discovery_timeout
        attempt = 0
        while True:
            attempt += 1
            text = xapp(service, f"{label}-{ric}-nodes-{attempt}")
            found = {int(n) for n in re.findall(
                r"^\s*\d+\s+(\d+)\s+505\s+1\s+gNB\s*$",
                text, re.MULTILINE)}
            if found == expected and f"Connected E2 nodes: {len(expected)}" in text:
                print(f"PASS: {label}, RIC {ric.upper()} nodes={sorted(found)}",
                      flush=True)
                return
            require(retry and time.monotonic() < deadline,
                    f"{label}: RIC {ric} expected {sorted(expected)}, got {sorted(found)}")
            time.sleep(2)

    def kpm(group, label):
        ric, expected, _, service = group
        text = xapp(service, f"{label}-{ric}-kpm")
        subscribed = {int(n) for n in re.findall(r"Subscribed: node=(\d+)", text)}
        reported = {int(n) for n in re.findall(r"KPM node=(\d+)", text)}
        require(subscribed == reported == expected,
                f"{label}: RIC {ric} unexpected KPM nodes")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(expected),
                f"{label}: RIC {ric} subscription cleanup incomplete")
        require(not any(marker in text for marker in
                        ("Assertion", "Traceback", "callback error:")),
                f"{label}: RIC {ric} xApp error")
        print(f"PASS: {label}, RIC {ric.upper()} fresh KPM subscriptions",
              flush=True)

    run(compose + ["--profile", "tools", "config", "--quiet"], "config")
    before = snapshot("before")
    for group in GROUPS:
        nodes(group, "baseline")
        kpm(group, "baseline")

    if args.scenario == "ric-migration":
        migration = compose + [
            "-f", str(DEPLOY / "compose.ric-migration.yaml")]
        merged = json.loads(run(
            migration + ["--profile", "tools", "config", "--format", "json"],
            "migration-config"))
        service = merged["services"]["emulator-2"]
        mounts = [
            v for v in service["volumes"]
            if v["target"] == "/usr/local/etc/flexric/e2agent.conf"
        ]
        require(len(mounts) == 1 and mounts[0].get("read_only"),
                "Migration configuration mount must be unique and read-only")
        config = DEPLOY / "config/ric-recovery/e2agent-ric2.conf"
        require(Path(mounts[0]["source"]) == config,
                "Unexpected migration configuration path")
        require('NearRT_RIC_IP = "172.29.0.11"' in
                config.read_text(encoding="utf-8"),
                "Migration configuration must target RIC B")
        require(service["environment"]["FLEXRIC_EMULATOR_NB_ID"] == "2",
                "Migration must preserve node ID 2")

        def check_identities(reference, current, label):
            for name in SERVICES:
                require(reference[name]["image_id"] == current[name]["image_id"],
                        f"{label}: {name} image changed")
                if name == "emulator-2":
                    require(reference[name]["id"] != current[name]["id"],
                            f"{label}: Agent 2 was not recreated")
                    require(reference[name]["started_at"] !=
                            current[name]["started_at"],
                            f"{label}: Agent 2 startup time did not change")
                else:
                    for field in ("id", "started_at", "restart_count"):
                        require(reference[name][field] == current[name][field],
                                f"{label}: {name} {field} changed")
            print(f"PASS: {label}, only Agent 2 recreated", flush=True)

        recreate = [
            "up", "-d", "--no-build", "--pull", "never",
            "--force-recreate", "--no-deps", "emulator-2"]
        restore_needed = False
        try:
            restore_needed = True
            run(migration + recreate, "migrate-agent-2", timeout=90)
            migrated_groups = (
                ("a", {1}, "xapp-nodes", "xapp-kpm"),
                ("b", {2, 3}, "xapp-nodes-ric2", "xapp-kpm-ric2"),
            )
            for group in migrated_groups:
                nodes(group, "migrated", retry=True)
                kpm(group, "migrated")
            migrated = snapshot("migrated")
            check_identities(before, migrated, "migration")

            run(compose + recreate, "restore-agent-2", timeout=90)
            for group in GROUPS:
                nodes(group, "restored", retry=True)
                kpm(group, "restored")
            restored = snapshot("restored")
            check_identities(migrated, restored, "restoration")
            restore_needed = False

            summary = {
                "scenario": args.scenario,
                "result": "PASS",
                "before": before,
                "migrated": migrated,
                "restored": restored,
                "scope": (
                    "Explicit Agent 2 configuration migration from RIC A "
                    "to RIC B, fresh KPM subscriptions and baseline restoration"
                ),
            }
            (output / "summary.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            print("PASS: cross-RIC Agent migration and baseline restoration",
                  flush=True)
        finally:
            if restore_needed:
                print("Restoring Agent 2 after incomplete test...", flush=True)
                run(compose + recreate, "failure-restore-agent-2", timeout=90)
        print("Scope: explicit configuration change and Agent recreation; "
              "no automatic failover or old-subscription restoration.",
              flush=True)
        print(f"Logs and summary: {output}", flush=True)
        return

    since = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    restore_needed = False
    try:
        restore_needed = True
        run(compose + ["stop", "ric"], "stop-ric-a")
        state = json.loads(run(
            docker + ["inspect", before["ric"]["id"]], "ric-a-stopped"))[0]
        require(not state["State"]["Running"], "RIC A did not stop")

        deadline = time.monotonic() + args.discovery_timeout
        attempt = 0
        while True:
            attempt += 1
            detected = []
            for service in ("emulator", "emulator-2"):
                text = run(
                    compose + ["logs", "--no-color", "--since", since, service],
                    f"outage-{service}-{attempt}")
                require("Assertion" not in text, f"{service}: assertion during outage")
                detected.append(
                    "Communication with the nearRT-RIC lost" in text and
                    "E2 SETUP REQUEST timeout. Resending again" in text)
            if all(detected):
                break
            require(time.monotonic() < deadline, "Agent disconnect/retry not observed")
            time.sleep(2)
        print("PASS: both Agents detected disconnect and retried Setup", flush=True)

        nodes(GROUPS[1], "during-outage")
        kpm(GROUPS[1], "during-outage")
        run(compose + ["start", "ric"], "start-ric-a")
        for group in GROUPS:
            nodes(group, "recovered", retry=True)
            kpm(group, "recovered")
        after = snapshot("after")
        for service in SERVICES:
            require(before[service]["id"] == after[service]["id"],
                    f"{service}: container was recreated")
            require(before[service]["restart_count"] == after[service]["restart_count"],
                    f"{service}: restart count changed")
            if service != "ric":
                require(before[service]["started_at"] == after[service]["started_at"],
                        f"{service}: process was restarted")
        require(before["ric"]["started_at"] != after["ric"]["started_at"],
                "RIC A startup time did not change")
        restore_needed = False

        summary = {
            "scenario": args.scenario, "result": "PASS",
            "before": before, "after": after,
            "scope": "Graceful same-address RIC restart and fresh KPM subscriptions",
        }
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print("PASS: unchanged Agent and RIC B container identities and startup times",
              flush=True)
        print("PASS: graceful RIC A restart recovery", flush=True)
    finally:
        if restore_needed:
            print("Restoring RIC A after incomplete test...", flush=True)
            run(compose + ["start", "ric"], "restore-ric-a")
    print("Scope: no abrupt crash, cross-RIC failover or old-subscription restoration.",
          flush=True)
    print(f"Logs and summary: {output}", flush=True)


if __name__ == "__main__":
    main()
