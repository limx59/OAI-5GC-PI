#!/usr/bin/env python3
"""Validate bounded OCUDU/OAI UE UDP traffic using fresh-container rounds."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time

spec = importlib.util.spec_from_file_location(
    "connectivity", Path(__file__).with_name("validate-zmq-connectivity.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
run, require = base.run, base.require
DOCKER, NAMES = base.DOCKER, base.NAMES
SERVER = "oai-pi-ocudu-traffic"
IMAGE = "limx59/oai-pi-oai-nr-ue:arm64-zmq-test"

def exists(name):
    r = run(DOCKER + ["ps", "-a", "--filter",
                      f"name=^/{name}$", "--format", "{{.Names}}"])
    r.check_returncode()
    return bool(r.stdout.strip())

def save_command(directory, label, cmd, timeout=30):
    r = run(cmd, timeout)
    (directory / f"{label}.stdout").write_text(r.stdout)
    (directory / f"{label}.stderr").write_text(r.stderr)
    r.check_returncode()
    return r

def ping(directory, label):
    r = save_command(directory, label, DOCKER + [
        "exec", NAMES[1], "ping", "-n", "-I", "oaitun_ue1",
        "-c", "5", "-W", "2", "172.22.0.151"], 20)
    require(base.re.search(r"5 (?:packets )?received", r.stdout),
            f"{label}: expected 5/5 replies")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/ocudu-zmq-udp"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    compose = DOCKER + [
        "compose", "-f", str(root / "deploy/ocudu/compose.zmq.yaml"),
        "-f", str(root / "deploy/ocudu/compose.zmq-worker-test.yaml"),
        "--profile", "ue"]
    require(not exists(SERVER), "Traffic container already exists")
    for name in NAMES:
        r = run(DOCKER + ["ps", "--filter",
                          f"name=^/{name}$", "--format", "{{.Names}}"])
        r.check_returncode()
        require(not r.stdout.strip(), f"Experiment already running: {name}")
    r = run(DOCKER + ["network", "inspect", "docker_open5gs_default"])
    r.check_returncode()
    network = json.loads(r.stdout)[0]
    require(not any(v.get("IPv4Address", "").split("/")[0] == "172.22.0.151"
                    for v in network.get("Containers", {}).values()),
            "Traffic endpoint address is occupied")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    summary = {
        "passed": False, "rounds": [],
        "scope": "1 Mbps UDP, 10 seconds per direction, fresh-container rounds",
        "limitations": "No continuous RNTI/context monitoring or RF validation"}
    print(f"Evidence: {output}", flush=True)
    try:
        for number in range(1, args.rounds + 1):
            directory = output / f"round-{number}"
            directory.mkdir()
            item = {"number": number, "passed": False, "cleanup_errors": []}
            summary["rounds"].append(item)
            owned_server = False
            ran_attempted = False
            baseline = None
            try:
                # Omit --rm: explicit removal avoids the observed auto-remove race.
                save_command(directory, "server-start", DOCKER + [
                    "run", "-d", "--pull", "never", "--name", SERVER,
                    "--network", "docker_open5gs_default", "--ip", "172.22.0.151",
                    "--cap-add", "NET_ADMIN", "--entrypoint", "/bin/sh", IMAGE,
                    "-c", "ip route add 192.168.100.0/24 via 172.22.0.8 && "
                    "exec timeout --signal=INT --kill-after=5s 300s "
                    "iperf3 -s -B 172.22.0.151"], 45)
                owned_server = True
                ran_attempted = True
                save_command(directory, "ran-start", compose + [
                    "up", "-d", "--force-recreate", "--no-build",
                    "--pull", "never", "gnb", "nrue"], 60)
                baseline = base.states()
                item["before"] = baseline
                deadline = time.monotonic() + 60
                ip = base.address()
                while not ip:
                    base.states()
                    require(time.monotonic() < deadline, "UE address timeout")
                    time.sleep(1)
                    ip = base.address()
                item["ue_ip"] = ip
                ping(directory, "ping-before")
                for direction in ("uplink", "downlink"):
                    require(base.states() == baseline, "Process identity changed")
                    require(base.address() == ip, "UE address changed")
                    cmd = DOCKER + [
                        "exec", NAMES[1], "timeout", "--kill-after=5s", "40s",
                        "iperf3", "-c", "172.22.0.151", "-B", ip,
                        "--bind-dev", "oaitun_ue1", "-u", "-b", "1M",
                        "-l", "1200", "-t", "10", "-J", "--get-server-output"]
                    if direction == "downlink":
                        cmd.append("-R")
                    r = save_command(directory, direction, cmd, 50)
                    data = json.loads(r.stdout)
                    require("error" not in data, f"{direction}: iperf error")
                    received = data["end"]["sum_received"]
                    bps, loss = received["bits_per_second"], received["lost_percent"]
                    item[direction] = {
                        "offered_bps": 1000000, "received_bps": bps,
                        "lost_percent": loss, "bytes": received["bytes"]}
                    require(received["bytes"] > 0 and bps >= 800000 and loss <= 5,
                            f"{direction}: throughput/loss threshold failed")
                    require(base.states() == baseline, "Process identity changed")
                    require(base.address() == ip, "UE address changed")
                    print(f"PASS: round {number} {direction}: "
                          f"{bps:.0f} bit/s, loss={loss:.3f}%", flush=True)
                ping(directory, "ping-after")
                item["after"] = base.states()
                require(item["after"] == baseline, "Process identity changed")
                require(base.address() == ip, "UE address changed")
                item["checks_passed"] = True
            except Exception as exc:
                item["error"] = str(exc)
                raise
            finally:
                if ran_attempted:
                    for name in NAMES:
                        try:
                            cmd = DOCKER + ["logs", "--timestamps"]
                            if baseline:
                                cmd += ["--since", baseline[name][3]]
                            r = run(cmd + [name], 30)
                            r.check_returncode()
                            lines = [s for s in (r.stdout + r.stderr).splitlines()
                                     if not base.SENSITIVE.search(s)]
                            (directory / f"{name}.log").write_text(
                                "\n".join(lines) + "\n")
                        except Exception as exc:
                            item["cleanup_errors"].append(f"Log capture: {exc}")
                    try:
                        save_command(directory, "ran-stop",
                                     compose + ["stop", "nrue", "gnb"], 45)
                        r = run(DOCKER + ["inspect", *NAMES])
                        r.check_returncode()
                        require(all(not i["State"]["Running"]
                                    for i in json.loads(r.stdout)),
                                "Experiment still running")
                    except Exception as exc:
                        item["cleanup_errors"].append(str(exc))
                if owned_server:
                    try:
                        save_command(directory, "server-remove",
                                     DOCKER + ["rm", "-f", SERVER], 30)
                        deadline = time.monotonic() + 10
                        while exists(SERVER):
                            require(time.monotonic() < deadline,
                                    "Traffic container remains")
                            time.sleep(0.5)
                    except Exception as exc:
                        item["cleanup_errors"].append(str(exc))
            require(not item["cleanup_errors"], str(item["cleanup_errors"]))
            item["passed"] = True
            print(f"PASS: round {number}, cleanup complete", flush=True)
        summary["passed"] = True
    except Exception as exc:
        summary["error"] = str(exc)
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)

if __name__ == "__main__":
    main()
