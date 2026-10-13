#!/usr/bin/env python3
"""Record OAI KPM CSV during separate RFSim UE uplink and downlink tests."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

DEPLOY = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
METRICS = {"DRB.UEThpDl", "DRB.UEThpUl"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xapp-image",
                        default="limx59/flexric-xapp:arm64-multi-agent")
    parser.add_argument("--pull-policy", choices=("always", "never"),
                        default="always")
    parser.add_argument("--server", default="172.22.0.151")
    parser.add_argument("--node-id", type=int, default=3584)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-kpm-recording"))
    args = parser.parse_args()
    ipaddress.IPv4Address(args.server)
    require(args.node_id > 0, "Node ID must be positive.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="oai-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)

    docker = ["sudo", "docker"]
    compose = docker + ["compose", "-f", str(DEPLOY / "compose.oai.yaml")]
    config = DEPLOY / "config/oai/xapp.conf"
    require(config.is_file(), f"Missing configuration: {config}")

    address = subprocess.run(
        compose + ["exec", "-T", "nrue", "ip", "-4", "-j",
                   "addr", "show", "dev", "oaitun_ue1"],
        capture_output=True, text=True, check=True, timeout=20)
    addresses = [
        info["local"] for interface in json.loads(address.stdout)
        for info in interface.get("addr_info", [])
        if info.get("family") == "inet"
    ]
    require(len(addresses) == 1, "Expected one UE TUN IPv4 address.")
    ue_ip = addresses[0]
    print(f"UE TUN address: {ue_ip}", flush=True)

    if args.pull_policy == "always":
        with (output / "image-pull.log").open("w", encoding="utf-8") as stream:
            result = subprocess.run(
                docker + ["pull", args.xapp_image], stdout=stream,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=120)
        require(result.returncode == 0, "Image pull failed; inspect image-pull.log.")
    else:
        (output / "image-pull.log").write_text(
            "Pull skipped: using local image.\n", encoding="utf-8")
    image = subprocess.run(
        docker + ["image", "inspect", args.xapp_image, "--format",
                  "{{json .RepoDigests}}"],
        capture_output=True, text=True, check=True, timeout=20)
    (output / "image-digests.json").write_text(image.stdout, encoding="utf-8")

    summaries = []
    for direction, active_metric in (
        ("uplink", "DRB.UEThpUl"), ("downlink", "DRB.UEThpDl"),
    ):
        traffic_log = output / f"{direction}-iperf.json"
        xapp_log = output / f"{direction}-xapp.log"
        csv_path = output / f"{direction}.csv"
        name = f"oai-kpm-csv-{uuid.uuid4().hex[:12]}"
        traffic = compose + [
            "exec", "-T", "nrue", "timeout", "--kill-after=5s", "45s",
            "iperf3", "-c", args.server, "-B", ue_ip,
            "--bind-dev", "oaitun_ue1", "-u", "-b", "1M",
            "-l", "1200", "-t", "30", "-J",
        ]
        if direction == "downlink":
            traffic.append("-R")

        def run_traffic():
            started = datetime.now(timezone.utc)
            result = subprocess.run(
                traffic, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=55)
            traffic_log.write_text(result.stdout, encoding="utf-8")
            (output / f"{direction}-iperf.stderr.log").write_text(
                result.stderr, encoding="utf-8")
            return result, started, datetime.now(timezone.utc)

        print(f"Running {direction} traffic and CSV recording...", flush=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            transfer = pool.submit(run_traffic)
            time.sleep(3)
            try:
                with xapp_log.open("w", encoding="utf-8") as stream:
                    recorder = subprocess.run(
                        docker + [
                            "run", "--rm", "--pull", "never", "--name", name,
                            "--network", "oai-pi-flexric-lab",
                            "--mount", f"type=bind,src={config},"
                            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
                            "--mount", f"type=bind,src={output},dst=/evidence",
                            "-e", f"XAPP_OUTPUT=/evidence/{direction}.csv",
                            args.xapp_image, "xapp_kpm_recorder.py",
                            "-c", "/usr/local/etc/flexric/xapp.conf",
                        ], stdout=stream, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, timeout=60)
            finally:
                subprocess.run(
                    docker + ["rm", "-f", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, timeout=20)
            result, traffic_started, traffic_finished = transfer.result()

        require(result.returncode == 0,
                f"{direction}: traffic failed; inspect {traffic_log}")
        transfer_data = json.loads(result.stdout)
        require("error" not in transfer_data,
                f"{direction}: iperf reported an error.")
        received = transfer_data["end"]["sum_received"]
        require(received["bits_per_second"] > 0 and received["bytes"] > 0,
                f"{direction}: no traffic received.")
        require(recorder.returncode == 0,
                f"{direction}: recorder failed; inspect {xapp_log}")

        text = xapp_log.read_text(encoding="utf-8")
        subscriptions = re.findall(r"Subscribed: node=(\d+)", text)
        require(subscriptions == [str(args.node_id)],
                f"{direction}: unexpected subscriptions {subscriptions}")
        for marker in (
            "CSV callback error:", "KPM callback error:", "Skipping mismatched",
            "Unsupported KPM format:", "Assertion", "Traceback",
        ):
            require(marker not in text, f"{direction}: {marker}; inspect {xapp_log}")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 1,
                f"{direction}: subscription deletion incomplete.")

        with csv_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            required = {
                "received_at_utc", "node_id", "mcc", "mnc",
                "indication_format", "incomplete", "measurement",
                "value_type", "value",
            }
            require(required <= set(reader.fieldnames or []),
                    f"Missing CSV columns: {csv_path}")
            rows = list(reader)
        require(rows, f"Empty CSV: {csv_path}")
        counts = Counter()
        reports = defaultdict(lambda: defaultdict(list))
        for number, row in enumerate(rows, start=2):
            context = f"{csv_path}, row {number}"
            require(int(row["node_id"]) == args.node_id,
                    f"Unexpected node: {context}")
            require(int(row["mcc"]) == 1 and int(row["mnc"]) == 1,
                    f"Unexpected PLMN: {context}")
            metric = row["measurement"]
            require(metric in METRICS, f"Unexpected metric: {context}")
            require(row["indication_format"] in ("1", "3"),
                    f"Unsupported format: {context}")
            require(row["incomplete"] == "0", f"Incomplete record: {context}")
            require(row["value_type"] in ("integer", "real"),
                    f"Missing numeric value: {context}")
            value = float(row["value"])
            require(math.isfinite(value) and value >= 0,
                    f"Invalid throughput: {context}")
            stamp = datetime.fromisoformat(row["received_at_utc"])
            require(stamp.utcoffset() is not None
                    and stamp.utcoffset().total_seconds() == 0,
                    f"Non-UTC timestamp: {context}")
            require(traffic_started <= stamp <= traffic_finished,
                    f"Measurement outside traffic process window: {context}")
            counts[metric] += 1
            reports[stamp][metric].append(value)

        require(set(counts) == METRICS, f"Missing metrics: {csv_path}")
        timestamps = sorted(reports)
        positive = sum(
            any(value > 0 for value in reports[stamp].get(active_metric, []))
            for stamp in timestamps[1:]
        )
        require(positive >= 2,
                f"{direction}: fewer than two positive active-direction reports "
                "after excluding the first report.")
        summary = {
            "direction": direction, "ue_ip": ue_ip, "node_id": args.node_id,
            "csv_rows": len(rows), "metric_rows": dict(counts),
            "report_timestamps": len(timestamps),
            "active_metric": active_metric,
            "positive_reports_excluding_first": positive,
            "first_report": dict(reports[timestamps[0]]),
            "traffic_started_utc": traffic_started.isoformat(),
            "traffic_finished_utc": traffic_finished.isoformat(),
            "iperf_receiver": received,
        }
        summaries.append(summary)
        (output / "summary.json").write_text(
            json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
        print(f"PASS: {direction}, node={args.node_id}, CSV rows={len(rows)}, "
              f"positive later reports={positive}, subscription cleanup complete",
              flush=True)
        print(f"  iperf receiver={received['bits_per_second']:.0f} bit/s",
              flush=True)

    print("Scope: RFSim traffic and KPM recording; measurement accuracy "
          "and physical RF are not established.", flush=True)
    print(f"Logs and CSV: {output}", flush=True)


if __name__ == "__main__":
    main()
