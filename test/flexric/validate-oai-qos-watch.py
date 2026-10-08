#!/usr/bin/env python3
"""Validate QoS alert logic during OAI RFSim UE uplink/downlink traffic."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
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
    parser.add_argument("--server", default="172.22.0.151")
    parser.add_argument("--node-id", type=int, default=3584)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-qos-validation"))
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
    result = subprocess.run(
        compose + ["exec", "-T", "nrue", "ip", "-4", "-j",
                   "addr", "show", "dev", "oaitun_ue1"],
        capture_output=True, text=True, check=True, timeout=20)
    addresses = [
        info["local"] for interface in json.loads(result.stdout)
        for info in interface.get("addr_info", [])
        if info.get("family") == "inet"
    ]
    require(len(addresses) == 1, "Expected one UE TUN IPv4 address.")
    ue_ip = addresses[0]
    print(f"UE TUN address: {ue_ip}", flush=True)

    with (output / "image-pull.log").open("w", encoding="utf-8") as stream:
        pulled = subprocess.run(
            docker + ["pull", args.xapp_image], stdout=stream,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=120)
    require(pulled.returncode == 0, "Image pull failed; inspect image-pull.log.")
    image = subprocess.run(
        docker + ["image", "inspect", args.xapp_image, "--format",
                  "{{json .RepoDigests}}"],
        capture_output=True, text=True, check=True, timeout=20)
    (output / "image-digests.json").write_text(image.stdout, encoding="utf-8")

    summaries = []
    for direction, active_metric in (
        ("uplink", "DRB.UEThpUl"), ("downlink", "DRB.UEThpDl"),
    ):
        for case, threshold in (("alerts", 1e9), ("no-alerts", 0.0)):
            label = f"{direction}-{case}"
            log = output / f"{label}-qos.log"
            name = f"oai-qos-{uuid.uuid4().hex[:12]}"
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
                (output / f"{label}-iperf.json").write_text(
                    result.stdout, encoding="utf-8")
                (output / f"{label}-iperf.stderr.log").write_text(
                    result.stderr, encoding="utf-8")
                return result, started, datetime.now(timezone.utc)

            print(f"Running {label}...", flush=True)
            with ThreadPoolExecutor(max_workers=1) as pool:
                transfer = pool.submit(run_traffic)
                time.sleep(3)
                try:
                    qos_started = datetime.now(timezone.utc)
                    with log.open("w", encoding="utf-8") as stream:
                        watcher = subprocess.run(
                            docker + [
                                "run", "--rm", "--pull", "never", "--name", name,
                                "--network", "oai-pi-flexric-lab",
                                "--mount", f"type=bind,src={config},"
                                "dst=/usr/local/etc/flexric/xapp.conf,readonly",
                                "-e", f"XAPP_QOS_THRESHOLD={threshold}",
                                "-e", "XAPP_QOS_LOW_REPORTS=2",
                                args.xapp_image, "xapp_qos_watch.py",
                                "-c", "/usr/local/etc/flexric/xapp.conf",
                            ], stdout=stream, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, timeout=60)
                    qos_finished = datetime.now(timezone.utc)
                finally:
                    subprocess.run(
                        docker + ["rm", "-f", name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL, timeout=20)
                result, started, finished = transfer.result()

            require(result.returncode == 0,
                    f"{label}: traffic failed; inspect evidence logs.")
            traffic_data = json.loads(result.stdout)
            require("error" not in traffic_data, f"{label}: iperf error.")
            received = traffic_data["end"]["sum_received"]
            require(received["bytes"] > 0 and received["bits_per_second"] > 0,
                    f"{label}: no traffic received.")
            require(watcher.returncode == 0,
                    f"{label}: xApp failed; inspect {log}")
            require(started <= qos_started < qos_finished <= finished,
                    f"{label}: QoS process not contained in traffic process window.")

            text = log.read_text(encoding="utf-8")
            subscriptions = re.findall(r"Subscribed: node=(\d+)", text)
            require(subscriptions == [str(args.node_id)],
                    f"{label}: unexpected subscriptions {subscriptions}")
            require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 1,
                    f"{label}: subscription deletion incomplete.")
            for marker in (
                "callback error:", "Skipping mismatched", "Unsupported KPM format:",
                "Assertion", "Traceback", "UNKNOWN:", "RECOVERY:",
            ):
                require(marker not in text, f"{label}: {marker}; inspect {log}")

            values = defaultdict(list)
            alerts = Counter()
            for line in text.splitlines():
                measurement = re.fullmatch(
                    r"QoS: node=(\d+) metric=(\S+) mean=(\S+) samples=(\d+)",
                    line.strip())
                if measurement:
                    node, metric, mean, samples = measurement.groups()
                    require(int(node) == args.node_id and metric in METRICS,
                            f"{label}: unexpected measurement identity.")
                    value = float(mean)
                    require(math.isfinite(value) and value >= 0 and int(samples) > 0,
                            f"{label}: invalid measurement.")
                    if case == "alerts":
                        require(value < threshold,
                                f"{label}: test threshold too low.")
                    values[metric].append(value)
                alert = re.fullmatch(
                    r"ALERT: node=(\d+) metric=(\S+) below (\S+) for "
                    r"(\d+) consecutive reports\.", line.strip())
                if alert:
                    node, metric, limit, consecutive = alert.groups()
                    require(case == "alerts" and int(node) == args.node_id
                            and metric in METRICS, f"{label}: unexpected alert.")
                    require(float(limit) == threshold and int(consecutive) == 2
                            and len(values[metric]) == 2,
                            f"{label}: alert must follow two observations.")
                    alerts[metric] += 1

            require(set(values) == METRICS
                    and all(len(samples) >= 3 for samples in values.values()),
                    f"{label}: missing metric observations.")
            if case == "alerts":
                require(set(alerts) == METRICS
                        and all(count == 1 for count in alerts.values()),
                        f"{label}: missing or repeated alerts.")
            else:
                require(not alerts and "ALERT:" not in text,
                        f"{label}: unexpected alert.")
            positive = sum(value > 0 for value in values[active_metric][1:])
            require(positive >= 2,
                    f"{label}: insufficient later active-direction positive means.")

            summaries.append({
                "case": label, "ue_ip": ue_ip, "node_id": args.node_id,
                "threshold": threshold, "required_consecutive_reports": 2,
                "observations": {metric: len(samples)
                                 for metric, samples in values.items()},
                "alerts": dict(alerts), "active_metric": active_metric,
                "positive_active_means_excluding_first": positive,
                "first_means": {metric: samples[0]
                                for metric, samples in values.items()},
                "traffic_started_utc": started.isoformat(),
                "traffic_finished_utc": finished.isoformat(),
                "qos_started_utc": qos_started.isoformat(),
                "qos_finished_utc": qos_finished.isoformat(),
                "iperf_receiver": received,
            })
            (output / "summary.json").write_text(
                json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
            print(f"PASS: {label}, node={args.node_id}, "
                  f"alerts={sum(alerts.values())}, later positive means={positive}, "
                  "subscription cleanup complete", flush=True)

    print("Scope: forced-threshold alert logic with RFSim traffic; "
          "no SLA or measurement-accuracy claim.", flush=True)
    print(f"Logs and summary: {output}", flush=True)


if __name__ == "__main__":
    main()
