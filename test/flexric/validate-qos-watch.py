#!/usr/bin/env python3
"""Validate independent QoS alerts in running FlexRIC emulator topologies."""

import argparse
from collections import Counter
import math
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

DEPLOY = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
METRICS = {"DRB.UEThpDl", "DRB.UEThpUl"}


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
                        default=Path("/tmp/flexric-qos-validation"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(
        prefix=f"{args.scenario}-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)
    groups = [("a", {1, 2, 3}, "emulator")]
    if args.scenario == "multi-ric":
        groups = [("a", {1, 2}, "emulator"), ("b", {3}, "multi-ric")]

    docker = ["sudo", "docker"]
    for label, nodes, folder in groups:
        expected = {(node, metric) for node in nodes for metric in METRICS}
        config = DEPLOY / "config" / folder / "xapp.conf"
        require(config.is_file(), f"Configuration missing: {config}")
        for case, threshold in (("alerts", 1e9), ("no-alerts", 0.0)):
            name = f"flexric-qos-{uuid.uuid4().hex[:12]}"
            log = output / f"ric-{label}-{case}.log"
            command = docker + [
                "run", "--rm", "--pull", args.pull_policy, "--name", name,
                "--network", "oai-pi-flexric-lab",
                "--mount", f"type=bind,src={config},"
                "dst=/usr/local/etc/flexric/xapp.conf,readonly",
                "-e", f"XAPP_QOS_THRESHOLD={threshold}",
                "-e", "XAPP_QOS_LOW_REPORTS=2",
                args.xapp_image, "xapp_qos_watch.py",
                "-c", "/usr/local/etc/flexric/xapp.conf",
            ]
            try:
                with log.open("w", encoding="utf-8") as stream:
                    result = subprocess.run(
                        command, stdout=stream, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, timeout=60)
                require(result.returncode == 0,
                        f"{case}: exit {result.returncode}; inspect {log}")
            finally:
                subprocess.run(
                    docker + ["rm", "-f", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, timeout=20)

            text = log.read_text(encoding="utf-8")
            subscribed = {int(n) for n in re.findall(
                r"Subscribed: node=(\d+)", text)}
            require(subscribed == nodes,
                    f"Unexpected subscribed nodes; inspect {log}")
            require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(nodes),
                    f"Subscription deletion incomplete; inspect {log}")
            for error in ("callback error:", "Skipping mismatched",
                          "Unsupported KPM format:", "Assertion", "Traceback",
                          "UNKNOWN:", "RECOVERY:"):
                require(error not in text,
                        f"Unexpected {error}; inspect {log}")

            observed = Counter()
            alerts = Counter()
            for line in text.splitlines():
                measurement = re.fullmatch(
                    r"QoS: node=(\d+) metric=(\S+) mean=(\S+) samples=(\d+)",
                    line.strip())
                if measurement:
                    node, metric, mean, samples = measurement.groups()
                    key = (int(node), metric)
                    require(key in expected, f"Unexpected identity; inspect {log}")
                    value = float(mean)
                    require(math.isfinite(value) and value >= 0
                            and int(samples) > 0,
                            f"Invalid measurement; inspect {log}")
                    if case == "alerts":
                        require(value < threshold,
                                f"Test threshold too low; inspect {log}")
                    observed[key] += 1
                alert = re.fullmatch(
                    r"ALERT: node=(\d+) metric=(\S+) below (\S+) for "
                    r"(\d+) consecutive reports.", line.strip())
                if alert:
                    node, metric, limit, consecutive = alert.groups()
                    key = (int(node), metric)
                    require(case == "alerts" and key in expected,
                            f"Unexpected alert; inspect {log}")
                    require(float(limit) == threshold and int(consecutive) == 2,
                            f"Incorrect alert parameters; inspect {log}")
                    require(observed[key] == 2,
                            f"Alert did not follow two observations; inspect {log}")
                    alerts[key] += 1
            require(set(observed) == expected
                    and all(count >= 2 for count in observed.values()),
                    f"Missing node/metric observations; inspect {log}")
            if case == "alerts":
                require(set(alerts) == expected
                        and all(count == 1 for count in alerts.values()),
                        f"Missing or repeated alerts; inspect {log}")
            else:
                require(not alerts and "ALERT:" not in text,
                        f"Unexpected low-throughput alert; inspect {log}")
            print(f"PASS: RIC {label.upper()}, {case}, nodes={sorted(nodes)}, "
                  f"metric pairs={len(observed)}, alerts={sum(alerts.values())}, "
                  "subscription cleanup complete", flush=True)

    print(f"Logs: {output}", flush=True)


if __name__ == "__main__":
    main()
