#!/usr/bin/env python3
"""Validate OCUDU DU KPM CSV with bounded UDP fresh-container rounds."""
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


RIC = "oai-pi-ocudu-zmq-lab-ric-1"

def ric_state():
    r = run(DOCKER + ["inspect", RIC])
    r.check_returncode()
    data = json.loads(r.stdout)[0]
    require(data["State"]["Running"], "RIC is not running")
    return [data["Id"], data["Image"], data["State"]["Pid"],
            data["State"]["StartedAt"], data["RestartCount"]]

def record_during(directory, direction, traffic_cmd, root, image):
    import csv
    import math
    from datetime import datetime, timezone

    def now():
        return datetime.now(timezone.utc)

    phase = directory / direction
    phase.mkdir()
    csv_path = phase / "kpm.csv"

    # Extend the existing demo only in an evidence-directory copy.
    demo = (root / "test/xapp/xapp_kpm.py").read_text()
    old = "            time.sleep(10)"
    require(demo.count(old) == 1, "Unexpected demo duration anchor")
    demo = demo.replace(old, "            time.sleep(20)", 1)
    old = "        while ric.try_stop == 0:"
    require(demo.count(old) == 1, "Unexpected demo shutdown anchor")
    demo = demo.replace(old, (
        '        print("KPM_DELETE_COMPLETE_UTC=" + '
        '__import__("datetime").datetime.now('
        '__import__("datetime").timezone.utc).isoformat(), flush=True)\n'
        '        time.sleep(6)\n' + old
    ), 1)
    compile(demo, "xapp_kpm.py", "exec")
    demo_path = phase / "xapp_kpm.py"
    demo_path.write_text(demo)

    name = f"ocudu-kpm-{directory.parent.name}-{directory.name}-{direction}"
    created = None
    process = None
    before_ric = ric_state()
    started = now()
    stdout_path = phase / "recorder.stdout"
    stderr_path = phase / "recorder.stderr"

    try:
        r = save_command(phase, "recorder-create", DOCKER + [
            "create", "--pull", "never", "--name", name,
            "--network", "docker_open5gs_default", "--ulimit", "core=0",
            "--mount",
            f"type=bind,src={root}/deploy/ocudu/config/xapp.conf,"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "--mount", f"type=bind,src={phase},dst=/evidence",
            "--mount",
            f"type=bind,src={demo_path},"
            "dst=/opt/oai-pi/test/xapp/xapp_kpm.py,readonly",
            "-e", "XAPP_OUTPUT=/evidence/kpm.csv",
            "--entrypoint", "timeout", image,
            "--signal=INT", "--kill-after=5s", "45s",
            "python3", "-u", "xapp_kpm_recorder.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ], 30)
        created = r.stdout.strip()

        with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
            process = subprocess.Popen(
                DOCKER + ["start", "-a", created],
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            )
            deadline = time.monotonic() + 15
            while "Subscribed: node=420" not in stdout_path.read_text():
                require(process.poll() is None,
                        "Recorder exited before subscription; inspect phase logs")
                require(time.monotonic() < deadline,
                        "KPM subscription readiness timeout")
                time.sleep(0.2)

            traffic_started = now()
            traffic = save_command(directory, direction, traffic_cmd, 50)
            traffic_finished = now()
            process.wait(timeout=45)

        r = run(DOCKER + ["inspect", created])
        r.check_returncode()
        state = json.loads(r.stdout)[0]["State"]
        require(not state["Running"] and state["ExitCode"] == 0,
                f"Recorder failed: {state['ExitCode']}")
        output = stdout_path.read_text() + stderr_path.read_text()
        for failure in (
            "CSV callback error", "Skipping mismatched",
            "Unsupported KPM format", "Assertion", "Traceback",
        ):
            require(failure not in output, f"Recorder error: {failure}")
        require("SUBSCRIPTION DELETE RESPONSE rx" in output,
                "Missing subscription delete response")
        marker = "KPM_DELETE_COMPLETE_UTC="
        markers = [line.split(marker, 1)[1].strip()
                   for line in output.splitlines() if marker in line]
        require(len(markers) == 1, "Missing or ambiguous deletion marker")
        deleted = datetime.fromisoformat(markers[0])

        with csv_path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        require(bool(rows), "CSV has no measurements")
        expected = {"DRB.UEThpDl", "DRB.UEThpUl"}
        require({row["measurement"] for row in rows} == expected,
                "CSV metrics do not match configuration")

        timestamps = set()
        for row in rows:
            require(row["node_id"] == "420", "Unexpected node")
            require((row["mcc"], row["mnc"]) == ("1", "1"),
                    "Unexpected PLMN")
            require(row["ran_type"] == "7", "Expected gNB-DU")
            require(row["indication_format"] == "3", "Expected Format 3")
            require(row["incomplete"] == "0", "Incomplete measurement")
            require(row["value_type"] in ("integer", "real"),
                    "Missing numeric measurement")
            value = float(row["value"])
            require(math.isfinite(value) and value >= 0,
                    "Invalid numeric measurement")
            received = datetime.fromisoformat(row["received_at_utc"])
            require(received.utcoffset() is not None,
                    "Timestamp lacks timezone")
            require((received - deleted).total_seconds() <= 1,
                    "CSV callback observed over 1s after deletion completion")
            timestamps.add(received)

        metric = "DRB.UEThpUl" if direction == "uplink" else "DRB.UEThpDl"
        positive = [
            row for row in rows
            if row["measurement"] == metric
            and float(row["value"]) > 0
            and (datetime.fromisoformat(row["received_at_utc"])
                 - traffic_started).total_seconds() >= 2
            and (datetime.fromisoformat(row["received_at_utc"])
                 - traffic_finished).total_seconds() <= 2
        ]
        require(len(positive) >= 2,
                f"{direction}: expected at least two later positive reports")

        # Observe the sender as well as callbacks; local RLC collection continues.
        r = run(DOCKER + [
            "logs", "--timestamps", "--since", started.isoformat(), NAMES[0]
        ], 30)
        r.check_returncode()
        lines = [
            line for line in (r.stdout + r.stderr).splitlines()
            if base.re.search(r"\[E2[^]]*\]", line)
        ]
        (phase / "gnb-e2.log").write_text("\n".join(lines) + "\n")
        responses, sends = [], []
        for line in lines:
            if ("Sending subscription delete response" not in line
                    and "Sending E2 indication" not in line):
                continue
            stamp = datetime.fromisoformat(
                line.split()[0].replace("Z", "+00:00"))
            if "Sending subscription delete response" in line:
                responses.append(stamp)
            if "Sending E2 indication" in line:
                sends.append(stamp)
        require(len(responses) == 1, "Expected one gNB deletion response")
        require(bool(sends), "No gNB indications observed")
        require(not any((stamp - responses[0]).total_seconds() > 1
                        for stamp in sends),
                "gNB continued indications over 1s after deletion response")
        observed_until = now()
        require((observed_until - deleted).total_seconds() >= 5,
                "Insufficient post-deletion observation")
        require(ric_state() == before_ric, "RIC identity changed")

        ordered = sorted(timestamps)
        gaps = [(b - a).total_seconds()
                for a, b in zip(ordered, ordered[1:])]
        details = {
            "csv_rows": len(rows),
            "receive_timestamps": len(ordered),
            "positive_later_reports": len(positive),
            "load_metric": metric,
            "receive_gaps_seconds": gaps,
            "traffic_started_utc": traffic_started.isoformat(),
            "traffic_finished_utc": traffic_finished.isoformat(),
            "deletion_completed_utc": deleted.isoformat(),
            "observed_until_utc": observed_until.isoformat(),
            "cleanup_observation": "no sends/callbacks later than 1s; >=5s guard",
        }
        (phase / "summary.json").write_text(json.dumps(details, indent=2) + "\n")
        print(f"PASS: {direction} CSV rows={len(rows)}, "
              f"positive later reports={len(positive)}, deletion guard passed",
              flush=True)
        return traffic, details
    finally:
        if created:
            r = run(DOCKER + ["rm", "-f", created], 30)
            (phase / "recorder-remove.log").write_text(r.stdout + r.stderr)
            r.check_returncode()
        if process is not None and process.poll() is None:
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/ocudu-zmq-kpm"))
    parser.add_argument("--xapp-image", default=
        "oai-pi-ocudu-flexric-xapp:e2ap3-kpm3-node-id-fix")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    compose = DOCKER + [
        "compose", "-f", str(root / "deploy/ocudu/compose.zmq.yaml"),
        "-f", str(root / "deploy/ocudu/compose.zmq-worker-test.yaml"),
        "-f", str(root / "deploy/ocudu/compose.e2.yaml"),
        "--profile", "ue"]
    ric_state()
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
        "scope": "DU KPM CSV with 1 Mbps UDP, 10s per direction, fresh RAN rounds",
        "limitations": "No continuous RNTI/context monitoring; UE index is not a "
                       "real UE identifier; units/accuracy and 1s wall-clock "
                       "cadence unvalidated; no RF; RIC/core retained"}
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
                item["ric_before"] = ric_state()
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
                    r, kpm = record_during(
                        directory, direction, cmd, root, args.xapp_image)
                    item[direction + "_kpm"] = kpm
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
                require(ric_state() == item["ric_before"],
                        "RIC identity changed during round")
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
                                     if base.re.search(
                                         r"\[E2[^]]*\]|RRC Setup Procedure|"
                                         r"PDU Session Resource Setup Procedure|"
                                         r"UE Context Release Procedure", s)
                                     and not base.SENSITIVE.search(s)]
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
