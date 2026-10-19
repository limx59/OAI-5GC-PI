#!/usr/bin/env python3
"""Validate KPM Style 1 or 4 on the current OCUDU deployment."""

import argparse
import csv
from datetime import datetime
import importlib.util
import json
from pathlib import Path
from statistics import median
import subprocess
import tempfile
import uuid

DOCKER = ["sudo", "docker"]
NAMES = [
    "oai-pi-ocudu-zmq-lab-gnb-1",
    "oai-pi-ocudu-zmq-lab-nrue-1",
    "oai-pi-ocudu-zmq-lab-ric-1",
]
DIGEST = "sha256:bff13777799f436cb3abdfa9e5433fd7f306c8d8898c69b26b9e664b4160b844"
SERVER_IMAGE = "limx59/oai-pi-oai-nr-ue:arm64-zmq-test"
XAPP_IMAGE = "limx59/oai-pi-ocudu-flexric-xapp:arm64-kpm-styles-test"


def command(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def states():
    values = json.loads(command(["inspect", *NAMES]))
    result = {}
    for value in values:
        if not value["State"]["Running"]:
            raise RuntimeError(f"Container stopped: {value['Name']}")
        result[value["Name"].lstrip("/")] = {
            "id": value["Id"],
            "image_id": value["Image"],
            "image": value["Config"]["Image"],
            "pid": value["State"]["Pid"],
            "started": value["State"]["StartedAt"],
            "restarts": value["RestartCount"],
            "cpuset": value["HostConfig"]["CpusetCpus"],
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", type=int, choices=(1, 4), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "kpm_existing", root / "test/ocudu/validate-zmq-kpm.py")
    existing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(existing)

    # Adapt an in-memory helper copy; repository helpers remain unchanged.
    helper_path = root / "test/ocudu/validate-zmq-kpm.py"
    helper = helper_path.read_text()

    def adapt(old, new):
        nonlocal helper
        if helper.count(old) != 1:
            raise RuntimeError(f"Unexpected helper anchor: {old!r}")
        helper = helper.replace(old, new, 1)

    expected_format = "1" if args.style == 1 else "3"
    adapt(
        'require(row["indication_format"] == "3", "Expected Format 3")',
        f'require(row["indication_format"] == "{expected_format}", '
        f'"Expected Format {expected_format}")',
    )
    adapt(
        '"create", "--pull", "never", "--name", name,',
        '"create", "--pull", "never", '
        f'"-e", "OAI_PI_KPM_REPORT_STYLE={args.style}", "--name", name,',
    )
    adapt(
        '"logs", "--timestamps", "--since", started.isoformat(), NAMES[0]\n'
        '        ], 30)',
        '"logs", "--timestamps", "--since", started.isoformat(),\n'
        '            "--until", now().isoformat(), NAMES[0]\n'
        '        ], 120)',
    )
    exec(compile(helper, str(helper_path), "exec"), existing.__dict__)

    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix=f"ocudu-kpm-style{args.style}-", dir=parent))
    print(f"Evidence: {dest}", flush=True)
    server = None
    summary = {
        "passed": False,
        "scope": "Style 1/4 directional traffic, report format and normal deletion",
        "style": args.style,
        "expected_indication_format": expected_format,
        "xapp_image": XAPP_IMAGE,
        "limitations": "Short traffic regression; source age and metric accuracy not established",
        "cadence_criteria": {
            "median_min_s": 0.95, "median_max_s": 1.05,
            "gap_min_s": 0.8, "gap_max_s": 1.2,
        },
        "directions": {},
        "cleanup_errors": [],
    }
    try:
        before = states()
        summary["before"] = before
        if not before[NAMES[0]]["image"].endswith("@" + DIGEST):
            raise RuntimeError("Unexpected deployment image")
        if (
            before[NAMES[0]]["cpuset"],
            before[NAMES[1]]["cpuset"],
        ) != ("0-2", "3"):
            raise RuntimeError("Unexpected RAN CPU allocation")
        ip = existing.base.address()
        if not ip:
            raise RuntimeError("UE has no tunnel address")
        summary["ue_ip"] = ip

        network = json.loads(command([
            "network", "inspect", "docker_open5gs_default"
        ]))[0]
        if any(
            value.get("IPv4Address", "").split("/")[0] == "172.22.0.151"
            for value in network.get("Containers", {}).values()
        ):
            raise RuntimeError("Traffic endpoint address is occupied")

        name = "ocudu-kpm-traffic-" + uuid.uuid4().hex[:12]
        server = command([
            "create", "--pull", "never", "--name", name,
            "--network", "docker_open5gs_default",
            "--ip", "172.22.0.151",
            "--cap-add", "NET_ADMIN",
            "--entrypoint", "/bin/sh", SERVER_IMAGE,
            "-ec",
            "ip route add 192.168.100.0/24 via 172.22.0.8; "
            "exec timeout --signal=INT --kill-after=5s 300s "
            "iperf3 -s -B 172.22.0.151",
        ]).strip()
        command(["start", server])
        existing.ping(dest, "ping-before")

        for direction in ("uplink", "downlink"):
            if states() != before or existing.base.address() != ip:
                raise RuntimeError(
                    "Deployment identity or UE address changed")
            traffic_cmd = DOCKER + [
                "exec", NAMES[1],
                "timeout", "--kill-after=5s", "40s",
                "iperf3", "-c", "172.22.0.151", "-B", ip,
                "--bind-dev", "oaitun_ue1",
                "-u", "-b", "1M", "-l", "1200",
                "-t", "10", "-J", "--get-server-output",
            ]
            if direction == "downlink":
                traffic_cmd.append("-R")
            traffic, details = existing.record_during(
                dest, direction, traffic_cmd, root, XAPP_IMAGE)
            output = (dest / direction / "recorder.stdout").read_text()
            marker = f"selected KPM action format = {args.style}"
            if marker not in output:
                raise RuntimeError("Missing SDK action-format selection marker")
            item = {"kpm": details}
            summary["directions"][direction] = item

            data = json.loads(traffic.stdout)
            if "error" in data:
                raise RuntimeError(f"{direction}: {data['error']}")
            received = data["end"]["sum_received"]
            item["traffic"] = received
            if not (
                received["bytes"] > 0
                and received["bits_per_second"] >= 800000
                and received["lost_percent"] <= 5
            ):
                raise RuntimeError(
                    f"{direction}: throughput/loss threshold failed")

            gaps = details["receive_gaps_seconds"]
            if len(gaps) < 10:
                raise RuntimeError(
                    f"{direction}: insufficient report intervals")
            item["cadence"] = {
                "intervals": len(gaps),
                "min_s": min(gaps),
                "median_s": median(gaps),
                "max_s": max(gaps),
            }
            if not (
                0.95 <= median(gaps) <= 1.05
                and min(gaps) >= 0.8
                and max(gaps) <= 1.2
            ):
                raise RuntimeError(
                    f"{direction}: cadence outside trial criteria")

            with (dest / direction / "kpm.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            start = datetime.fromisoformat(details["traffic_started_utc"])
            end = datetime.fromisoformat(details["traffic_finished_utc"])
            active_times = sorted({
                datetime.fromisoformat(row["received_at_utc"])
                for row in rows
                if start <= datetime.fromisoformat(
                    row["received_at_utc"]) <= end
            })
            item["reports_during_traffic"] = len(active_times)
            if len(active_times) < 7:
                raise RuntimeError(
                    f"{direction}: insufficient reports during traffic")
            if states() != before or existing.base.address() != ip:
                raise RuntimeError(
                    "Deployment identity or UE address changed")
            print(
                f"PASS: {direction}, "
                f"rate={received['bits_per_second']:.0f} bit/s, "
                f"loss={received['lost_percent']:.3f}%, "
                f"report median={median(gaps):.3f}s, "
                f"max={max(gaps):.3f}s",
                flush=True,
            )

        existing.ping(dest, "ping-after")
        summary["after"] = states()
        if summary["after"] != before:
            raise RuntimeError("Deployment identity changed")
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
    finally:
        if server:
            try:
                log = command(["logs", "--timestamps", server])
                (dest / "traffic-server.log").write_text(log)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
            try:
                command(["rm", "--force", server])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if summary["cleanup_errors"]:
            summary["passed"] = False
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")

    print(f"Evidence retained: {dest}")
    if not summary["passed"]:
        print(json.dumps(summary, indent=2))
        raise SystemExit(1)
    print(f"PASS: Style {args.style}; UL/DL traffic, expected report format, "
          "numeric records, cadence and normal deletion.")
    print("Existing gNB, UE, RIC and shared core retained.")


if __name__ == "__main__":
    main()
