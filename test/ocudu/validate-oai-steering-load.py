#!/usr/bin/env python3
"""Validate OAI RFSim low-high-low response before sequential comparison."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from qos_startup_guard import wait_host_ready
from review_oai_steering_load import review

DOCKER = ["sudo", "docker"]
XAPP_IMAGE = "limx59/flexric-xapp:arm64-oai-steering-load-test@sha256:6074e3c22854de75f39efe613ff09db761d056e85a7204435e474e341cb96389"
RIC_IMAGE = "limx59/flexric-ric:arm64@sha256:c319a545ecdf024aca6360f93704bf3751f38894fbfb2dd851de48eee9d1225b"
GNB_IMAGE = "limx59/oai-gnb:arm64-radio-stats@sha256:c98427aef6794d7e00ab9368b6bd35819b81fc5e7deced4c3b040eedb90e82e3"
UE_IMAGE = "limx59/oai-nr-ue:arm64@sha256:230909b7e83f0fecd3ea1cca43d8d3e7b2834858da52367dfcb18f2f396af738"
BASE_RIC = "oai-pi-ocudu-zmq-lab-ric-1"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    require(result.returncode == 0, result.stderr.strip() or "Docker command failed")
    return result.stdout + result.stderr if args[0] == "logs" else result.stdout


def inspect(name):
    return json.loads(command(["inspect", name]))[0]


def identity(name):
    value = inspect(name)
    return {
        "id": value["Id"], "image": value["Image"],
        "pid": value["State"]["Pid"],
        "started": value["State"]["StartedAt"],
        "restarts": value["RestartCount"],
        "running": value["State"]["Running"],
    }


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="oai-steering-load-", dir=parent))
    print(f"Evidence: {dest}", flush=True)
    result = {
        "passed": False, "cleanup_errors": [],
        "scope": "Single OAI RFSim UE; six-phase throughput load response",
        "limitations": "Receipt-time association; no capacity or PRB equivalence claim",
    }
    project = "oai-steering-" + uuid.uuid4().hex[:12]
    compose = [
        "compose", "--project-name", project,
        "-f", str(root / "deploy/oai-flexric/compose.oai.yaml"),
    ]
    ran = None
    probe = server = attached = None
    baseline = None
    touched = False
    try:
        for name in (
            "oai-pi-ocudu-zmq-lab-gnb-1",
            "oai-pi-ocudu-zmq-lab-nrue-1",
        ):
            require(not inspect(name)["State"]["Running"],
                    "Stop experimental OCUDU RAN first")
        baseline = identity(BASE_RIC)
        require(baseline["running"], "Baseline RIC must remain running")
        result["baseline_ric_before"] = baseline
        for network, addresses in (
            ("oai-pi-flexric-lab", {"172.29.0.10", "172.29.0.30"}),
            ("docker_open5gs_default", {"172.22.0.150", "172.22.0.151"}),
        ):
            value = json.loads(command(["network", "inspect", network]))[0]
            occupied = {
                item.get("IPv4Address", "").split("/")[0]
                for item in value.get("Containers", {}).values()
            }
            require(not occupied.intersection(addresses),
                    f"Required test address occupied on {network}")
        result["images"] = {
            image: json.loads(command(["image", "inspect", image]))[0]["Id"]
            for image in (RIC_IMAGE, GNB_IMAGE, UE_IMAGE, XAPP_IMAGE)
        }
        require((root / "deploy/oai-flexric/config/oai/ue.conf").is_file(),
                "Prepared UE configuration missing")
        (dest / "xapp.conf").write_bytes(
            (root / "deploy/oai-flexric/config/oai/xapp.conf").read_bytes()
        )
        override = dest / "compose.ran.yaml"
        override.write_text(
            "services:\n"
            f"  ric:\n    image: {RIC_IMAGE}\n"
            f"  gnb:\n    image: {GNB_IMAGE}\n"
            f"  nrue:\n    image: {UE_IMAGE}\n"
        )
        ran = compose + ["-f", str(override)]
        result["host_readiness"] = wait_host_ready(dest / "host-readiness.json")
        touched = True
        command(ran + ["up", "-d", "--no-build", "--pull", "never", "ric"])
        time.sleep(2)
        command(ran + [
            "up", "-d", "--no-deps", "--no-build", "--pull", "never", "gnb",
        ], timeout=90)
        gnb = command(ran + ["ps", "-q", "gnb"]).strip()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            require(inspect(gnb)["State"]["Running"], "OAI gNB exited")
            log = command(["logs", gnb])
            if "E2 SETUP RESPONSE" in log and (
                "NGSetupResponse" in log or "associated AMF" in log
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("OAI NG/E2 setup timeout")
        command(ran + [
            "--profile", "ue", "up", "-d", "--no-deps",
            "--no-build", "--pull", "never", "nrue",
        ], timeout=90)
        ue = command(ran + ["--profile", "ue", "ps", "-q", "nrue"]).strip()
        deadline = time.monotonic() + 120
        ue_ip = None
        while time.monotonic() < deadline:
            require(inspect(ue)["State"]["Running"], "OAI UE exited")
            address = subprocess.run(
                DOCKER + ["exec", ue, "ip", "-j", "-4", "addr",
                          "show", "dev", "oaitun_ue1"],
                capture_output=True, text=True, timeout=15,
            )
            if address.returncode == 0:
                ips = [
                    a["local"] for item in json.loads(address.stdout)
                    for a in item.get("addr_info", [])
                    if a.get("family") == "inet"
                ]
                if len(ips) == 1:
                    ue_ip = ips[0]
                    break
            time.sleep(1)
        require(ue_ip is not None, "OAI UE tunnel timeout")
        result["ue_ip"] = ue_ip
        ric = command(ran + ["ps", "-q", "ric"]).strip()
        before = {name: identity(name) for name in (ric, gnb, ue)}
        server = command([
            "create", "--pull", "never", "--network", "docker_open5gs_default",
            "--ip", "172.22.0.151", "--cap-add", "NET_ADMIN",
            "--entrypoint", "/bin/sh", UE_IMAGE, "-ec",
            "ip route add 192.168.100.0/24 via 172.22.0.8; "
            "exec timeout --signal=INT --kill-after=5s 240s "
            "iperf3 -s -B 172.22.0.151",
        ]).strip()
        command(["start", server])
        time.sleep(1)
        command(["exec", ue, "ping", "-I", "oaitun_ue1",
                 "-c", "3", "-W", "3", "172.22.0.151"], timeout=20)
        env_file = dest / "compose-probe.env"
        env_file.write_text(
            f"OAI_STEERING_EVIDENCE={dest}\n"
            f"OAI_STEERING_XAPP_IMAGE={XAPP_IMAGE}\n"
        )
        collector = [
            "compose", "--project-name", project + "-collector",
            "--env-file", str(env_file), "-f",
            str(root / "deploy/ocudu/compose.oai-steering-load.yaml"),
        ]
        resolved = command(collector + ["config", "--format", "json"])
        (dest / "compose-probe.resolved.json").write_text(resolved)
        require(json.loads(resolved)["services"]["oai-steering-load"]["image"]
                == XAPP_IMAGE, "Unexpected collector image")
        command(collector + [
            "create", "--no-build", "--pull", "never", "oai-steering-load",
        ], timeout=60)
        probe = command(collector + [
            "ps", "--all", "-q", "oai-steering-load",
        ]).strip()
        require(inspect(probe)["Image"] == result["images"][XAPP_IMAGE],
                "Collector image mismatch")
        command(["cp", f"{probe}:/opt/oai-steering-load/collector.py",
                 str(dest / "packaged-collector.py")])
        original = (root / "test/ocudu/xapp-oai-steering-load.py").read_bytes()
        require((dest / "packaged-collector.py").read_bytes() == original,
                "Packaged collector differs from source")
        result["collector_sha256"] = hashlib.sha256(original).hexdigest()
        result["probe_launch"] = {
            "method": "docker compose create; docker start -a",
            "compose_file": "deploy/ocudu/compose.oai-steering-load.yaml",
            "image": XAPP_IMAGE,
        }
        with (dest / "probe.stdout").open("w") as out, \
             (dest / "probe.stderr").open("w") as err:
            attached = subprocess.Popen(
                DOCKER + ["start", "-a", probe],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            )
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                require(attached.poll() is None, "Collector exited early")
                if (dest / "probe.stdout").read_text().count("LOAD_REPORT=") >= 3:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Collector readiness timeout")
            result["phases"] = {}
            for direction in ("uplink", "downlink"):
                for phase, rate in (
                    ("low-before", 200000), ("high", 1000000),
                    ("low-after", 200000),
                ):
                    require(attached.poll() is None, "Collector exited during traffic")
                    key = f"{direction}-{phase}"
                    args = [
                        "exec", ue, "timeout", "--kill-after=5s", "30s",
                        "iperf3", "-c", "172.22.0.151", "-B", ue_ip,
                        "--bind-dev", "oaitun_ue1", "-u", "-b", str(rate),
                        "-l", "1200", "-t", "10", "-J", "--get-server-output",
                    ]
                    if direction == "downlink":
                        args.append("-R")
                    start = datetime.now(timezone.utc)
                    raw = command(args, timeout=40)
                    end = datetime.now(timezone.utc)
                    (dest / f"iperf-{key}.json").write_text(raw)
                    data = json.loads(raw)
                    require("error" not in data, "iperf reported an error")
                    result["phases"][key] = {
                        "direction": direction, "phase": phase,
                        "offered_bit_s": rate,
                        "started_utc": start.isoformat(),
                        "finished_utc": end.isoformat(),
                        "receiver": data["end"]["sum_received"],
                    }
                    print(f"TRAFFIC RECORDED: {key}", flush=True)
                    time.sleep(3)
            attached.wait(timeout=60)
        require(attached.returncode == 0, "Collector process failed")
        require(inspect(probe)["State"]["ExitCode"] == 0, "Collector exit failed")
        result["probe"] = json.loads((dest / "probe.json").read_text())
        with (dest / "kpm.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        result["load_response"] = review(rows, result["probe"], result["phases"])
        stdout = (dest / "probe.stdout").read_text()
        require(stdout.count("SUBSCRIPTION DELETE RESPONSE rx") == 1,
                "Expected one normal deletion response")
        require("KPM_DELETE_REJECTED" not in stdout, "Deletion rejected")
        require({name: identity(name) for name in before} == before,
                "OAI RAN/RIC identity changed")
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        for name in (probe, server):
            if name:
                try:
                    command(["rm", "-f", name])
                except Exception as error:
                    result["cleanup_errors"].append(str(error))
        if attached is not None:
            try:
                attached.wait(timeout=15)
            except Exception as error:
                result["cleanup_errors"].append(str(error))
        if touched:
            try:
                command(ran + ["--profile", "ue", "down"], timeout=90)
            except Exception as error:
                result["cleanup_errors"].append(str(error))
        if baseline is not None:
            try:
                result["baseline_ric_after"] = identity(BASE_RIC)
                require(result["baseline_ric_after"] == baseline,
                        "Baseline RIC changed")
            except Exception as error:
                result["cleanup_errors"].append(str(error))
        if result["cleanup_errors"]:
            result["passed"] = False
        (dest / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
        print(f"Evidence retained: {dest}", flush=True)
    if not result["passed"]:
        raise SystemExit(1)
    print("PASS: OAI six-phase load response; test containers removed.")


if __name__ == "__main__":
    main()
