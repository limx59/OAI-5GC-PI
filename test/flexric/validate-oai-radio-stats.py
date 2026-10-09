#!/usr/bin/env python3
"""Validate nonempty MAC/RLC/PDCP reports during OAI RFSim UE traffic."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

DEPLOY = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"
MODELS = {"MAC", "RLC", "PDCP"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xapp-image",
                        default="limx59/flexric-xapp:arm64-subscription-cleanup")
    parser.add_argument("--pull-policy", choices=("always", "never"),
                        default="always")
    parser.add_argument("--server", default="172.22.0.151")
    parser.add_argument("--node-id", type=int, default=3584)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-radio-stats"))
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
    for direction in ("uplink", "downlink"):
        log = output / f"{direction}-radio.log"
        name = f"oai-radio-{uuid.uuid4().hex[:12]}"
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
            (output / f"{direction}-iperf.json").write_text(
                result.stdout, encoding="utf-8")
            (output / f"{direction}-iperf.stderr.log").write_text(
                result.stderr, encoding="utf-8")
            return result, started, datetime.now(timezone.utc)

        print(f"Running {direction} traffic and radio statistics...", flush=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            transfer = pool.submit(run_traffic)
            time.sleep(3)
            try:
                xapp_started = datetime.now(timezone.utc)
                with log.open("w", encoding="utf-8") as stream:
                    watcher = subprocess.run(
                        docker + [
                            "run", "--rm", "--pull", "never", "--name", name,
                            "--network", "oai-pi-flexric-lab",
                            "--mount", f"type=bind,src={config},"
                            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
                            args.xapp_image, "xapp_radio_stats.py",
                            "-c", "/usr/local/etc/flexric/xapp.conf",
                        ], stdout=stream, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, timeout=60)
                xapp_finished = datetime.now(timezone.utc)
            finally:
                subprocess.run(
                    docker + ["rm", "-f", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, timeout=20)
            result, started, finished = transfer.result()

        require(result.returncode == 0,
                f"{direction}: traffic failed; inspect evidence logs.")
        traffic_data = json.loads(result.stdout)
        require("error" not in traffic_data, f"{direction}: iperf error.")
        received = traffic_data["end"]["sum_received"]
        require(received["bytes"] > 0 and received["bits_per_second"] > 0,
                f"{direction}: no traffic received.")
        require(watcher.returncode == 0,
                f"{direction}: xApp exit={watcher.returncode}; inspect {log}")
        require(started <= xapp_started < xapp_finished <= finished,
                f"{direction}: xApp outside traffic process window.")

        text = log.read_text(encoding="utf-8")
        for marker in ("callback error:", "Assertion", "Traceback",
                       "No subscriptions:"):
            require(marker not in text, f"{direction}: {marker}; inspect {log}")
        expected = {(model, args.node_id) for model in MODELS}
        subscribed = Counter(
            (model, int(node)) for model, node in re.findall(
                r"^Subscribed: (MAC|RLC|PDCP), node=(\d+)\s*$",
                text, re.MULTILINE))
        require(set(subscribed) == expected
                and all(count == 1 for count in subscribed.values()),
                f"{direction}: unexpected subscriptions; inspect {log}")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 3,
                f"{direction}: subscription deletion incomplete.")

        records = defaultdict(list)
        for model, node, count, timestamp in re.findall(
            r"^(MAC|RLC|PDCP) node=(\d+) records=(\d+) timestamp=(\d+)\s*$",
            text, re.MULTILINE):
            key = (model, int(node))
            require(key in expected, f"{direction}: unexpected report identity.")
            require(int(timestamp) > 0, f"{direction}: invalid report timestamp.")
            records[model].append(int(count))
        require(set(records) == MODELS
                and all(len(values) >= 2 for values in records.values()),
                f"{direction}: missing reports; inspect {log}")

        statistics = {}
        for model, values in sorted(records.items()):
            nonempty = sum(value > 0 for value in values)
            statistics[model] = {
                "reports": len(values), "nonempty": nonempty,
                "records_min": min(values), "records_max": max(values),
            }
        summary = {
            "direction": direction, "ue_ip": ue_ip, "node_id": args.node_id,
            "models": statistics,
            "traffic_started_utc": started.isoformat(),
            "traffic_finished_utc": finished.isoformat(),
            "xapp_started_utc": xapp_started.isoformat(),
            "xapp_finished_utc": xapp_finished.isoformat(),
            "iperf_receiver": received,
        }
        summaries.append(summary)
        (output / "summary.json").write_text(
            json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
        for model, stats in statistics.items():
            print(f"  {model}: {stats}", flush=True)
        require(all(stats["nonempty"] >= 2 for stats in statistics.values()),
                f"{direction}: each model needs two nonempty reports; inspect {log}")
        print(f"PASS: {direction}, node={args.node_id}, "
              "all three models nonempty, subscription cleanup complete",
              flush=True)

    print("Scope: report delivery and nonempty record lists; "
          "individual counter accuracy and physical RF are not established.",
          flush=True)
    print(f"Logs and summary: {output}", flush=True)


if __name__ == "__main__":
    main()
