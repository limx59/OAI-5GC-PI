#!/usr/bin/env python3
"""Validate emulator MAC/RLC/PDCP reporting in running FlexRIC topologies."""

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

DEPLOY = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
MODELS = {"MAC", "RLC", "PDCP"}


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
                        default=Path("/tmp/flexric-radio-stats"))
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
        expected = {(model, node) for model in MODELS for node in nodes}
        config = DEPLOY / "config" / folder / "xapp.conf"
        require(config.is_file(), f"Configuration missing: {config}")
        name = f"flexric-radio-{uuid.uuid4().hex[:12]}"
        log = output / f"ric-{label}-radio.log"
        command = docker + [
            "run", "--rm", "--pull", args.pull_policy, "--name", name,
            "--network", "oai-pi-flexric-lab",
            "--mount", f"type=bind,src={config},"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            args.xapp_image, "xapp_radio_stats.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ]
        try:
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    command, stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, timeout=60)
            require(result.returncode == 0,
                    f"RIC {label}: exit {result.returncode}; inspect {log}")
        finally:
            subprocess.run(
                docker + ["rm", "-f", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, timeout=20)

        text = log.read_text(encoding="utf-8")
        for error in ("callback error:", "Assertion", "Traceback",
                      "No subscriptions:"):
            require(error not in text,
                    f"RIC {label}: {error}; inspect {log}")
        subscribed = Counter(
            (model, int(node)) for model, node in re.findall(
                r"^Subscribed: (MAC|RLC|PDCP), node=(\d+)\s*$",
                text, re.MULTILINE))
        require(set(subscribed) == expected
                and all(count == 1 for count in subscribed.values()),
                f"Unexpected model/node subscriptions; inspect {log}")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(expected),
                f"Subscription cleanup incomplete; inspect {log}")

        records = defaultdict(list)
        for model, node, count, timestamp in re.findall(
            r"^(MAC|RLC|PDCP) node=(\d+) records=(\d+) timestamp=(\d+)\s*$",
            text, re.MULTILINE):
            key = (model, int(node))
            require(key in expected, f"Unexpected report identity; inspect {log}")
            require(int(timestamp) > 0, f"Invalid report timestamp; inspect {log}")
            records[key].append(int(count))
        require(set(records) == expected
                and all(len(values) >= 2 for values in records.values()),
                f"Missing model/node reports; inspect {log}")
        print(f"PASS: RIC {label.upper()}, nodes={sorted(nodes)}, "
              f"model/node pairs={len(records)}, subscription cleanup complete",
              flush=True)
        for (model, node), values in sorted(records.items()):
            nonempty = sum(value > 0 for value in values)
            print(f"  {model} node={node} reports={len(values)} "
                  f"nonempty={nonempty} records_min={min(values)} "
                  f"records_max={max(values)}", flush=True)
        if all(count == 0 for values in records.values() for count in values):
            print("  Scope: callback delivery passed; all record lists are empty.",
                  flush=True)

    print(f"Logs: {output}", flush=True)


if __name__ == "__main__":
    main()
