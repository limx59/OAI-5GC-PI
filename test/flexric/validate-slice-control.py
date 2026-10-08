#!/usr/bin/env python3
"""Validate custom SLICE control targeting in a running emulator topology."""

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
                        default=Path("/tmp/flexric-slice-validation"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(
        prefix=f"{args.scenario}-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)

    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    filenames = ["compose.emulator.yaml", "compose.multi-agent.yaml"]
    if args.scenario == "multi-ric":
        filenames.append("compose.multi-ric.yaml")
    for filename in filenames:
        compose += ["-f", str(DEPLOY / filename)]

    def run_xapp(label, value, folder=None, expected_status=0):
        name = f"flexric-slice-{uuid.uuid4().hex[:12]}"
        log = output / f"{label}.log"
        command = docker + [
            "run", "--rm", "--pull", args.pull_policy, "--name", name,
            "--network", "none" if folder is None else "oai-pi-flexric-lab",
        ]
        if value is not None:
            command += ["-e", f"XAPP_SLICE_NODE_ID={value}"]
        if folder is not None:
            config = DEPLOY / "config" / folder / "xapp.conf"
            require(config.is_file(), f"Configuration missing: {config}")
            command += ["--mount", f"type=bind,src={config},"
                        "dst=/usr/local/etc/flexric/xapp.conf,readonly"]
        command += [args.xapp_image, "xapp_slice_control.py",
                    "-c", "/usr/local/etc/flexric/xapp.conf"]
        try:
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    command, stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, timeout=60)
            require(result.returncode == expected_status,
                    f"{label}: exit {result.returncode}, expected "
                    f"{expected_status}; inspect {log}")
        finally:
            subprocess.run(
                docker + ["rm", "-f", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, timeout=20)
        return log.read_text(encoding="utf-8")

    for index, value in enumerate(("", "0", "-1", "abc", "65536",
                                   "999999999999999999999999")):
        text = run_xapp(f"invalid-id-{index}", value, expected_status=1)
        require("XAPP_SLICE_NODE_ID must be an integer in 1..65535." in text
                and "CONTROL-REQUEST tx" not in text
                and "E42 SETUP-REQUEST tx" not in text,
                f"Invalid ID {value!r} was not rejected before connection")
    print("PASS: six invalid node IDs rejected before RIC connection",
          flush=True)

    if args.scenario == "multi-agent":
        cases = [
            ("missing-node99", "99", "emulator", 99, None),
            ("default-node1", None, "emulator", 1, "emulator"),
            ("target-node2", "2", "emulator", 2, "emulator-2"),
        ]
    else:
        cases = [
            ("ric-a-missing-node3", "3", "emulator", 3, None),
            ("ric-a-target-node2", "2", "emulator", 2, "emulator-2"),
            ("ric-b-target-node3", "3", "multi-ric", 3, "emulator-3"),
        ]

    for label, value, folder, node, receiver in cases:
        since = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        text = run_xapp(label, value, folder,
                        expected_status=1 if receiver is None else 0)
        if receiver is None:
            require(f"ID {node}; found 0. No control sent." in text
                    and "CONTROL-REQUEST tx" not in text,
                    f"{label}: missing target was not rejected")
        else:
            require(f"control to lab node {node}." in text
                    and text.count("CONTROL-REQUEST tx") == 1
                    and text.count("Successfully received CONTROL-ACK") == 1,
                    f"{label}: target selection or acknowledgment failed")
            plans = [line.removeprefix("Proposed budgets: ")
                     for line in text.splitlines()
                     if line.startswith("Proposed budgets: ")]
            require(len(plans) == 1, f"{label}: missing policy plan")
            budgets = [entry["recommended_prb_percent"]
                       for entry in json.loads(plans[0])["slices"]]
            require(len(budgets) == 3
                    and all(abs(a - b) < 1e-6
                            for a, b in zip(budgets, (45, 40, 15))),
                    f"{label}: unexpected proposed budgets {budgets}")
            require("callback error:" not in text and "Traceback" not in text,
                    f"{label}: unexpected xApp error")

        for service in AGENTS:
            log = output / f"{label}-{service}.log"
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    compose + ["logs", "--no-color", "--since", since, service],
                    stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, timeout=30)
            require(result.returncode == 0, f"Cannot collect {log}")
            events = log.read_text(encoding="utf-8")
            expected = 1 if service == receiver else 0
            require(events.count("SLICE CONTROL ADD rx") == expected,
                    f"{label}: unexpected reception at {service}; inspect {log}")
            require(events.count("CONTROL ACKNOWLEDGE tx") == expected,
                    f"{label}: unexpected ACK count at {service}; inspect {log}")
        print(f"PASS: {label}, receiver={receiver or 'none'}, "
              "control reception isolated", flush=True)

    print("Scope: emulator delivery and ACK; scheduler changes are not applied.",
          flush=True)
    print(f"Logs: {output}", flush=True)


if __name__ == "__main__":
    main()
