#!/usr/bin/env python3
"""Validate Python steering mappings and emulator control routing."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

DEPLOY = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
AGENTS = ("emulator", "emulator-2", "emulator-3")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("multi-agent", "multi-ric"),
                        required=True)
    parser.add_argument("--xapp-image",
                        default="limx59/flexric-xapp:arm64-multi-agent")
    parser.add_argument("--pull-policy", choices=("always", "missing", "never"),
                        default="always")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-steering-validation"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(
        prefix=f"{args.scenario}-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)
    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    files = ["compose.emulator.yaml", "compose.multi-agent.yaml"]
    if args.scenario == "multi-ric":
        files.append("compose.multi-ric.yaml")
    for filename in files:
        compose += ["-f", str(DEPLOY / filename)]

    def run_case(label, node, status=0, folder=None, mode="recommendation"):
        mapping = {"ran_ue_id": 1,
                   "cells": {"cell-a": node << 8, "cell-b": (node + 1) << 8}}
        loads = {"cell-a": 0.5, "cell-b": 0.5} if mode == "balanced" else {
            "cell-a": 0.9, "cell-b": 0.2}
        samples = [{"time_s": t, "cells": loads} for t in (0, 1)]
        if mode == "invalid-later":
            samples.append({"time_s": 2,
                            "cells": {"cell-a": 1.1, "cell-b": 0.2}})
        for suffix, data in (("mapping", mapping), ("samples", samples)):
            (output / f"{label}-{suffix}.json").write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8")
        name = f"flexric-steering-{uuid.uuid4().hex[:12]}"
        command = docker + [
            "run", "--rm", "--pull", args.pull_policy, "--name", name,
            "--network", "none" if folder is None else "oai-pi-flexric-lab",
            "--mount", f"type=bind,src={output},dst=/fixtures,readonly",
        ]
        if folder is not None:
            config = DEPLOY / "config" / folder / "xapp.conf"
            require(config.is_file(), f"Configuration missing: {config}")
            command += ["--mount", f"type=bind,src={config},"
                        "dst=/usr/local/etc/flexric/xapp.conf,readonly"]
        command += [args.xapp_image, "xapp_steering_control.py",
                    f"/fixtures/{label}-samples.json", "--mapping",
                    f"/fixtures/{label}-mapping.json"]
        if folder is not None or mode == "invalid-later":
            command += [
                "--send-emulator", "--config",
                "/usr/local/etc/flexric/xapp.conf", "--binary",
                "/usr/local/bin/flexric/xApp/c/xapp_handover_control",
            ]
        log = output / f"{label}.log"
        try:
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    command, stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, timeout=60)
            require(result.returncode == status,
                    f"{label}: exit {result.returncode}, expected {status}; "
                    f"inspect {log}")
        finally:
            subprocess.run(
                docker + ["rm", "-f", name], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=20)
        return log.read_text(encoding="utf-8")

    def selection(text, node):
        lines = [line.removeprefix("Selected first recommendation: ")
                 for line in text.splitlines()
                 if line.startswith("Selected first recommendation: ")]
        require(len(lines) == 1, "Expected one selected recommendation")
        request = json.loads(lines[0])
        require(request["source_nr_cgi"] == node << 8
                and request["target_nr_cgi"] == (node + 1) << 8
                and request["ran_ue_id"] == 1
                and request["executed"] is False,
                "Unexpected selected request")

    for node in (1, 2, 3):
        text = run_case(f"dry-node{node}", node)
        selection(text, node)
        require("Dry run:" in text and "E42 SETUP-REQUEST tx" not in text
                and "CONTROL-REQUEST tx" not in text, "Dry run connected")
    for node in (0, 65536):
        text = run_case(f"invalid-source{node}", node, status=2)
        require("lab gNB ID in 1..65535" in text
                and "CONTROL-REQUEST tx" not in text, "Invalid source accepted")
    text = run_case("balanced", 2, mode="balanced")
    require("No qualifying steering recommendation; no control sent." in text
            and "CONTROL-REQUEST tx" not in text, "Balanced input sent control")
    text = run_case("invalid-later", 2, status=2, mode="invalid-later")
    require("Selected first recommendation:" not in text
            and "E42 SETUP-REQUEST tx" not in text
            and "CONTROL-REQUEST tx" not in text, "Invalid later input accepted")
    print("PASS: multi-source dry runs, source bounds, balanced and invalid input",
          flush=True)

    cases = [("missing-node99", 99, "emulator", None),
             ("source-node2", 2, "emulator", "emulator-2")]
    if args.scenario == "multi-ric":
        cases = [("ric-a-missing-node3", 3, "emulator", None),
                 ("ric-a-source-node2", 2, "emulator", "emulator-2"),
                 ("ric-b-source-node3", 3, "multi-ric", "emulator-3")]
    for label, node, folder, receiver in cases:
        since = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        text = run_case(label, node, status=1 if receiver is None else 0,
                        folder=folder)
        selection(text, node)
        if receiver is None:
            require(f"Lab node {node} not found; no control sent." in text
                    and "CONTROL-REQUEST tx" not in text, "Missing node accepted")
        else:
            require(f"Selected lab node: PLMN 505/01, node ID {node}" in text
                    and text.count("CONTROL-REQUEST tx") == 1
                    and text.count("Successfully received CONTROL-ACK") == 1
                    and "Control process completed." in text,
                    f"{label}: control or ACK failed")
        for agent in AGENTS:
            log = output / f"{label}-{agent}.log"
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    compose + ["logs", "--no-color", "--since", since, agent],
                    stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, timeout=30)
            require(result.returncode == 0, f"Cannot collect {log}")
            events = log.read_text(encoding="utf-8")
            expected = 1 if agent == receiver else 0
            require(events.count("Recv control message for handover") == expected
                    and events.count("CONTROL ACKNOWLEDGE tx") == expected,
                    f"{label}: unexpected reception; inspect {log}")
            if expected:
                require(f"ran_ue_id 1 to target cell NR_CGI {(node + 1) << 8}"
                        in events, f"{label}: unexpected target CGI")
        print(f"PASS: {label}, receiver={receiver or 'none'}, "
              "control reception isolated", flush=True)
    print("Scope: synthetic policy-to-control communication; no real handover.",
          flush=True)
    print(f"Logs and inputs: {output}", flush=True)


if __name__ == "__main__":
    main()
