#!/usr/bin/env python3
"""Validate KPM CSV recording against a running FlexRIC emulator topology."""

import argparse
from collections import Counter
import csv
from datetime import datetime
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
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-kpm-recording"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(
        prefix=f"{args.scenario}-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)

    groups = [("a", {1, 2, 3}, "emulator")]
    if args.scenario == "multi-ric":
        groups = [("a", {1, 2}, "emulator"), ("b", {3}, "multi-ric")]

    docker = ["sudo", "docker"]
    for label, expected, folder in groups:
        config = DEPLOY / "config" / folder / "xapp.conf"
        require(config.is_file(), f"Configuration missing: {config}")
        name = f"flexric-csv-{uuid.uuid4().hex[:12]}"
        filename = f"ric-{label}.csv"
        log = output / f"ric-{label}.log"
        command = docker + [
            "run", "--rm", "--pull", "always", "--name", name,
            "--network", "oai-pi-flexric-lab",
            "--mount", f"type=bind,src={config},"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "--mount", f"type=bind,src={output},dst=/evidence",
            "-e", f"XAPP_OUTPUT=/evidence/{filename}",
            args.xapp_image, "xapp_kpm_recorder.py",
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
        subscribed = {int(value) for value in re.findall(
            r"Subscribed: node=(\d+)", text)}
        require(subscribed == expected,
                f"RIC {label}: unexpected subscriptions {subscribed}")
        for error in ("CSV callback error:", "KPM callback error:",
                      "Skipping mismatched", "Unsupported KPM format:",
                      "Assertion", "Traceback"):
            require(error not in text,
                    f"RIC {label}: {error}; inspect {log}")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(expected),
                f"RIC {label}: subscription deletion incomplete; inspect {log}")

        path = output / filename
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            required = {
                "received_at_utc", "node_id", "mcc", "mnc",
                "indication_format", "incomplete", "measurement",
                "value_type", "value",
            }
            require(required <= set(reader.fieldnames or []),
                    f"Missing CSV columns: {path}")
            rows = list(reader)
        require(rows, f"CSV contains no measurements: {path}")
        counts = Counter()
        for number, row in enumerate(rows, start=2):
            context = f"{path}, row {number}"
            node = int(row["node_id"])
            require(node in expected, f"Unexpected node: {context}")
            require(int(row["mcc"]) == 505 and int(row["mnc"]) == 1,
                    f"Unexpected PLMN: {context}")
            require(row["measurement"] in METRICS,
                    f"Unexpected measurement: {context}")
            require(row["indication_format"] in ("1", "3"),
                    f"Unsupported indication format: {context}")
            require(row["incomplete"] == "0",
                    f"Incomplete measurement: {context}")
            require(row["value_type"] in ("integer", "real"),
                    f"Missing numeric value: {context}")
            value = float(row["value"])
            require(math.isfinite(value) and value >= 0,
                    f"Invalid throughput: {context}")
            timestamp = datetime.fromisoformat(row["received_at_utc"])
            require(timestamp.utcoffset() is not None
                    and timestamp.utcoffset().total_seconds() == 0,
                    f"Timestamp is not UTC: {context}")
            counts[node, row["measurement"]] += 1
        require(set(counts) == {(node, metric)
                               for node in expected for metric in METRICS},
                f"Missing node/metric combinations: {path}")
        print(f"PASS: RIC {label.upper()}, nodes={sorted(expected)}, "
              f"CSV rows={len(rows)}, subscription cleanup complete",
              flush=True)
        for (node, metric), count in sorted(counts.items()):
            print(f"  node={node} metric={metric} rows={count}", flush=True)

    print(f"Logs and CSV: {output}", flush=True)


if __name__ == "__main__":
    main()
