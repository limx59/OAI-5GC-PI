#!/usr/bin/env python3
"""Test emulator Agent 2 recreation in an already running FlexRIC topology."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
DEPLOY = HERE.parents[1] / "deploy/oai-flexric"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("multi-agent", "multi-ric"),
                        required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-agent-recovery"))
    parser.add_argument("--discovery-timeout", type=int, default=90)
    args = parser.parse_args()
    if args.discovery_timeout < 1:
        parser.error("--discovery-timeout must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    compose = ["sudo", "docker", "compose"]
    files = ["compose.emulator.yaml", "compose.multi-agent.yaml"]
    if args.scenario == "multi-ric":
        files.append("compose.multi-ric.yaml")
    for filename in files:
        compose += ["-f", str(DEPLOY / filename)]

    def run(command, label, timeout=45):
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, stdin=subprocess.DEVNULL)
        path = args.output_dir / f"{label}.log"
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{label}: exit {result.returncode}; inspect {path}")
        return result.stdout

    def validate(label):
        output = run(
            [sys.executable, str(HERE / "validate-topology.py"),
             "--scenario", args.scenario, "--checks", "config", "nodes", "kpm",
             "--output-dir", str(args.output_dir / label)],
            label, timeout=180,
        )
        print(output.strip(), flush=True)

    rics = ["ric"]
    if args.scenario == "multi-ric":
        rics.append("ric-2")

    def ric_ids(label):
        identities = {}
        for service in rics:
            container = run(compose + ["ps", "-q", service],
                            f"{label}-{service}-id").strip()
            if not container:
                raise RuntimeError(f"{service}: running container not found")
            state = json.loads(run(
                ["sudo", "docker", "inspect", container],
                f"{label}-{service}-inspect",
            ))[0]
            if not state["State"]["Running"]:
                raise RuntimeError(f"{service}: container is not running")
            identities[service] = state["Id"]
        return identities

    def wait_nodes(expected, label):
        deadline = time.monotonic() + args.discovery_timeout
        attempt = 0
        while True:
            attempt += 1
            text = run(
                compose + ["--profile", "tools", "run", "-T", "--rm",
                           "--no-deps", "xapp-nodes"],
                f"{label}-attempt-{attempt}",
            )
            found = {int(value) for value in re.findall(
                r"^\s*\d+\s+(\d+)\s+505\s+1\s+gNB\s*$",
                text, re.MULTILINE,
            )}
            if (found == expected and
                    f"Connected E2 nodes: {len(expected)}" in text):
                print(f"PASS: {label}, RIC A nodes={sorted(found)}", flush=True)
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"{label}: expected {sorted(expected)}, got {sorted(found)}"
                )
            time.sleep(2)

    validate("baseline")
    before = ric_ids("before")
    restore_needed = True
    try:
        run(compose + ["stop", "emulator-2"], "stop-agent2")
        remaining = {1, 3} if args.scenario == "multi-agent" else {1}
        wait_nodes(remaining, "agent2-absent")

        run(compose + ["up", "-d", "--no-build", "--no-deps",
                       "--pull", "always", "--force-recreate", "emulator-2"],
            "recreate-agent2", timeout=120)
        restore_needed = False
        expected = {1, 2, 3} if args.scenario == "multi-agent" else {1, 2}
        wait_nodes(expected, "agent2-returned")
        validate("recovered")

        if ric_ids("after") != before:
            raise RuntimeError("RIC container identities changed")
        print("PASS: RIC containers remained running with unchanged identities",
              flush=True)
        print("PASS: Agent 2 recreation and fresh KPM subscriptions",
              flush=True)
    finally:
        if restore_needed:
            run(compose + ["up", "-d", "--no-build", "--no-deps", "emulator-2"],
                "restore-agent2", timeout=120)

    print(f"Logs: {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
