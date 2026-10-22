#!/usr/bin/env python3
"""Validate persistent QoS state across managed SDK session reconnection."""

from datetime import datetime, timedelta, timezone
import csv
import json
import math
from statistics import median
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
from qos_monitor_state import RULES, normalize
from qos_recovery_stream import RecoveryStream
import copy
import re

DOCKER = ["sudo", "docker"]
GNB = "oai-pi-ocudu-zmq-lab-gnb-1"
UE = "oai-pi-ocudu-zmq-lab-nrue-1"
BASE_RIC = "oai-pi-ocudu-zmq-lab-ric-1"
RIC_IMAGE = "limx59/oai-pi-ocudu-flexric-ric:arm64-kpm-csv-metadata-test"
XAPP_IMAGE = "limx59/oai-pi-ocudu-flexric-xapp:arm64-kpm-csv-metadata-test"
GNB_IMAGE = "limx59/oai-pi-ocudu-gnb:arm64-kpm-collection-clock"
SERVER_IMAGE = "limx59/oai-pi-oai-nr-ue:arm64-zmq-test"
TEST_IP = "172.22.0.163"


def command(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    if args and args[0] == "logs":
        return result.stdout + result.stderr
    return result.stdout


def inspect(name):
    return json.loads(command(["inspect", name]))[0]


def identity(name):
    value = inspect(name)
    return {
        "id": value["Id"], "image_id": value["Image"],
        "pid": value["State"]["Pid"],
        "started": value["State"]["StartedAt"],
        "restarts": value["RestartCount"],
        "running": value["State"]["Running"],
        "exit_code": value["State"]["ExitCode"],
        "oom_killed": value["State"].get("OOMKilled", False),
        "error": value["State"].get("Error", ""),
    }



def run_recovery(dest, ue_ip, summary):
    metric = "DRB.UEThpUl"
    stream = RecoveryStream((metric,))
    workers = []
    files = []
    traffic = None
    journal = (dest / "supervisor.events.jsonl").open("x")
    summary["sessions"] = []
    summary["mode"] = "advisory"
    summary["network_reconnection_tested"] = False
    summary["reconnection_method"] = "managed SDK process replacement"
    summary["same_process_automatic_reconnect_tested"] = False

    def record(events):
        for event in events:
            journal.write(json.dumps(event) + "\n")
            print("SUPERVISOR_EVENT " + json.dumps(event), flush=True)
        journal.flush()

    def pump():
        record(stream.poll())

    def wait_for(predicate, seconds, label, worker=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            pump()
            if predicate():
                return
            if worker is not None and worker["process"].poll() is not None:
                raise RuntimeError(f"SDK session exited while waiting: {label}")
            time.sleep(0.2)
        raise RuntimeError(f"Timeout: {label}")

    def observations(generation):
        return [
            row for row in stream.observations
            if row["generation"] == generation
        ]

    def start_session(number, duration):
        csv_path = dest / f"session-{number}.csv"
        record(stream.begin(csv_path))
        generation = stream.monitor.generation
        identifier = command([
            "create", "--pull", "never",
            "--name", "ocudu-qos-session-" + uuid.uuid4().hex[:12],
            "--network", "docker_open5gs_default",
            "--ulimit", "core=0",
            "--mount", f"type=bind,src={dest},dst=/evidence",
            "--mount", f"type=bind,src={dest}/xapp.conf,"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "-e", "OAI_PI_KPM_REPORT_STYLE=4",
            "-e", f"KPM_RECORD_SECONDS={duration}",
            "-e", f"XAPP_OUTPUT=/evidence/session-{number}.csv",
            "-e", f"PROBE_OUTPUT=/evidence/session-{number}.json",
            "--entrypoint", "timeout", XAPP_IMAGE,
            "--signal=INT", "--kill-after=5s", "80s",
            "python3", "-u", "/evidence/probe.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ]).strip()
        worker = {
            "number": number, "id": identifier,
            "generation": generation, "process": None,
        }
        workers.append(worker)
        out = (dest / f"session-{number}.stdout").open("w")
        err = (dest / f"session-{number}.stderr").open("w")
        files.extend((out, err))
        worker["process"] = subprocess.Popen(
            DOCKER + ["start", "-a", identifier],
            stdin=subprocess.DEVNULL, stdout=out, stderr=err,
        )
        return worker

    def finish_session(worker):
        process = worker["process"]
        wait_for(
            lambda: process.poll() is not None, 85,
            f"session {worker['number']} normal shutdown",
        )
        pump()
        state = inspect(worker["id"])["State"]
        number = worker["number"]
        if process.returncode or state["Running"] or state["ExitCode"]:
            raise RuntimeError(f"Session {number} did not exit successfully")
        result = json.loads((dest / f"session-{number}.json").read_text())
        if not result.get("passed"):
            raise RuntimeError(f"Session {number} callback validation failed")
        stdout = (dest / f"session-{number}.stdout").read_text()
        if stdout.count("SUBSCRIPTION DELETE RESPONSE rx") != 1:
            raise RuntimeError(f"Session {number}: expected one deletion response")
        if any(token in stdout for token in (
            "RIC_CONTROL_REQUEST", "KPM_DELETE_REJECTED",
        )):
            raise RuntimeError(f"Session {number}: unexpected control or rejection")
        ids = re.findall(r"xApp ID = (\d+)", stdout)
        if len(ids) != 1:
            raise RuntimeError(f"Session {number}: expected one assigned xApp ID")
        summary["sessions"].append({
            "number": number, "container_id": worker["id"],
            "generation": worker["generation"],
            "xapp_id": int(ids[0]), "probe": result,
        })

    def verify_fresh_alert(generation):
        first = observations(generation)[:3]
        if len(first) != 3:
            raise RuntimeError("Expected three initial UL observations")
        if [row["report_sequence"] for row in first] != [1, 2, 3]:
            raise RuntimeError("New SDK report sequence did not start at 1")
        for count, row in enumerate(first, 1):
            state = row["state_after"]
            if (row["incomplete"] != "0" or row["value"] is None
                    or not 0 <= row["value"] < 500
                    or state["bad_count"] != count):
                raise RuntimeError("Initial idle UL observations did not form a fresh streak")
            expected = "ALERT" if count == 3 else "OBSERVING"
            if state["status"] != expected:
                raise RuntimeError("Alert state inherited or entered prematurely")
        alerts = [
            event for event in stream.events
            if event["generation"] == generation
            and event["event"] == "ALERT"
            and event.get("report_sequence") == 3
        ]
        if len(alerts) != 1:
            raise RuntimeError("Expected a fresh alert on report 3")
        return first

    try:
        first = start_session(1, 7)
        wait_for(
            lambda: len(observations(first["generation"])) >= 3,
            25, "first session reports", first,
        )
        verify_fresh_alert(first["generation"])
        finish_session(first)

        wait_for(
            lambda: any(
                event["event"] == "STALE"
                and event["generation"] == first["generation"]
                for event in stream.events
            ),
            10, "silence detection after the first session",
        )
        old_keys = set(stream.monitor.states)
        if len(old_keys) != 1:
            raise RuntimeError("Expected one stable UL node/UE key")

        second = start_session(2, 35)
        snapshot = copy.deepcopy(stream.monitor.states)
        with (dest / "session-1.csv").open(newline="") as handle:
            old_row = next(
                row for row in csv.DictReader(handle)
                if row["measurement"] == metric
            )
        rejected = stream.consume(old_row, first["generation"])
        if rejected or stream.monitor.states != snapshot:
            raise RuntimeError("Old-generation replay changed new-session state")
        summary["old_generation_replay_check"] = {
            "passed": True,
            "basis": "explicit replay of a retained first-session row",
            "live_delayed_packet_injection": False,
        }

        wait_for(
            lambda: len(observations(second["generation"])) >= 3,
            25, "second session reports", second,
        )
        summary["fresh_session_observations"] = verify_fresh_alert(
            second["generation"]
        )
        if set(stream.monitor.states) != old_keys:
            raise RuntimeError("Node/UE identity changed between SDK sessions")

        started = datetime.now(timezone.utc)
        recovery_start = len(stream.events)
        out = (dest / "iperf-recovery.json").open("w")
        err = (dest / "iperf-recovery.stderr").open("w")
        files.extend((out, err))
        traffic = subprocess.Popen(
            DOCKER + [
                "exec", UE, "timeout", "--kill-after=5s", "30s",
                "iperf3", "-c", "172.22.0.151", "-B", ue_ip,
                "--bind-dev", "oaitun_ue1", "-u", "-b", "1000000",
                "-l", "1200", "-t", "10", "-J", "--get-server-output",
            ],
            stdin=subprocess.DEVNULL, stdout=out, stderr=err,
        )
        wait_for(
            lambda: traffic.poll() is not None,
            40, "recovery traffic completion", second,
        )
        if traffic.returncode:
            raise RuntimeError("Recovery iperf command failed")
        data = json.loads((dest / "iperf-recovery.json").read_text())
        if "error" in data:
            raise RuntimeError(data["error"])
        receiver = data["end"]["sum_received"]
        if (receiver["bits_per_second"] < 800000
                or receiver["lost_percent"] > 5):
            raise RuntimeError("Recovery traffic acceptance failed")
        recoveries = [
            event for event in stream.events[recovery_start:]
            if event["event"] == "RECOVERY"
            and event["generation"] == second["generation"]
        ]
        if len(recoveries) != 1:
            raise RuntimeError("Expected one UL recovery during traffic")
        recovery = recoveries[0]
        sequence = recovery["report_sequence"]
        preceding = [
            row for row in observations(second["generation"])
            if row["report_sequence"] <= sequence
        ][-3:]
        if (len(preceding) != 3 or any(
            row["value"] is None or row["value"] < 800
            or row["incomplete"] != "0" for row in preceding
        )):
            raise RuntimeError("Recovery lacks three consecutive high reports")
        if [row["report_sequence"] for row in preceding] != list(
            range(sequence - 2, sequence + 1)
        ):
            raise RuntimeError("Recovery report sequences are not consecutive")
        summary["recovery_traffic"] = {
            "started_utc": started.isoformat(),
            "receiver": receiver, "event": recovery,
            "preceding_observations": preceding,
        }
        finish_session(second)
        if summary["sessions"][0]["xapp_id"] == summary["sessions"][1]["xapp_id"]:
            raise RuntimeError("Expected distinct RIC-assigned SDK session IDs")
        summary["network_reconnection_tested"] = True
        summary["supervisor_pid"] = __import__("os").getpid()
        summary["stale_events"] = [
            event for event in stream.events if event["event"] == "STALE"
        ]
    finally:
        # Preserve supervisor evidence even if a worker or traffic command fails.
        (dest / "supervisor-observations.json").write_text(
            json.dumps(stream.observations, indent=2) + "\n"
        )
        for worker in workers:
            try:
                command(["rm", "-f", worker["id"]])
                process = worker["process"]
                if process is not None:
                    process.wait(timeout=15)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if traffic is not None and traffic.poll() is None:
            traffic.terminate()
            try:
                traffic.wait(timeout=5)
            except subprocess.TimeoutExpired:
                traffic.kill()
                traffic.wait()
        for handle in files:
            handle.close()
        journal.close()


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-qos-recovery-", dir=parent))
    print(f"Evidence: {dest}", flush=True)
    summary = {
        "passed": False,
        "scope": "Persistent UL QoS state across two managed SDK connections; advisory mode",
        "limitations": "Normal SDK-session shutdown and replacement; no same-process automatic reconnect, RIC restart or Agent restart",
        "comparison_criteria": {"minimum_reports": 5, "ratio_min": 0.70, "ratio_max": 1.50},
        "cleanup_errors": [],
    }
    temporary_ric = None
    probe = None
    server = None
    attached = None
    ran_touched = False
    before_ric = None

    base_files = (
        "deploy/ocudu/compose.zmq.yaml",
        "deploy/ocudu/compose.zmq-worker-test.yaml",
        "deploy/ocudu/compose.e2.yaml",
        "test/ocudu/patches/compose.kpm-collection-clock.yaml",
    )
    compose = ["compose"]
    for filename in base_files:
        compose += ["-f", str(root / filename)]

    try:
        for name in (GNB, UE):
            if inspect(name)["State"]["Running"]:
                raise RuntimeError("Stop the experimental gNB and UE first")
        before_ric = identity(BASE_RIC)
        if not before_ric["running"]:
            raise RuntimeError("Baseline RIC must remain running")
        summary["baseline_ric_before"] = before_ric

        network = json.loads(command([
            "network", "inspect", "docker_open5gs_default",
        ]))[0]
        if any(
            item.get("IPv4Address", "").split("/")[0] == TEST_IP
            for item in network.get("Containers", {}).values()
        ):
            raise RuntimeError("Temporary RIC address is occupied")
        summary["images"] = {
            image: json.loads(command(["image", "inspect", image]))[0]["Id"]
            for image in (RIC_IMAGE, XAPP_IMAGE, GNB_IMAGE, SERVER_IMAGE)
        }

        probe_source = root / "test/ocudu/xapp-qos-monitor.py"
        compile(probe_source.read_text(), str(probe_source), "exec")
        (dest / "probe.py").write_text(probe_source.read_text())
        (dest / "qos_monitor_state.py").write_text(
            (root / "test/ocudu/qos_monitor_state.py").read_text())

        for filename in ("ric.conf", "xapp.conf"):
            text = (root / "deploy/ocudu/config" / filename).read_text()
            if text.count('NearRT_RIC_IP = "172.22.0.162"') != 1:
                raise RuntimeError(f"Unexpected address anchor: {filename}")
            (dest / filename).write_text(text.replace(
                'NearRT_RIC_IP = "172.22.0.162"',
                f'NearRT_RIC_IP = "{TEST_IP}"', 1,
            ))
        text = (root / "deploy/ocudu/config/gnb-zmq-e2.yml").read_text()
        if text.count("  addrs: [172.22.0.162]") != 1:
            raise RuntimeError("Unexpected gNB E2 address anchor")
        (dest / "gnb.yml").write_text(text.replace(
            "  addrs: [172.22.0.162]", f"  addrs: [{TEST_IP}]", 1,
        ))
        override = dest / "compose.test.yaml"
        override.write_text(
            "services:\n  gnb:\n"
            f"    image: {GNB_IMAGE}\n"
            "    environment:\n"
            "      OAI_PI_TEST_REJECT_FIRST_DELETE: \"0\"\n"
            "    volumes:\n"
            f"      - {json.dumps(str(dest / 'gnb.yml') + ':/etc/ocudu/gnb.yml:ro')}\n"
        )

        temporary_ric = command([
            "create", "--pull", "never",
            "--name", "ocudu-rejection-ric-" + uuid.uuid4().hex[:12],
            "--network", "docker_open5gs_default", "--ip", TEST_IP,
            "--ulimit", "core=0",
            "--mount", f"type=bind,src={dest}/ric.conf,"
            "dst=/usr/local/etc/flexric/ric.conf,readonly",
            RIC_IMAGE,
        ]).strip()
        command(["start", temporary_ric])
        time.sleep(2)
        if not inspect(temporary_ric)["State"]["Running"]:
            raise RuntimeError("Temporary RIC exited")

        ran_touched = True
        output = command(
            compose + ["-f", str(override), "--profile", "ue",
                       "up", "-d", "--no-deps", "--force-recreate",
                       "--no-build", "--pull", "never", "gnb", "nrue"],
            timeout=90,
        )
        (dest / "ran-start.log").write_text(output)

        deadline = time.monotonic() + 90
        ue_ip = None
        while time.monotonic() < deadline:
            if not inspect(UE)["State"]["Running"]:
                raise RuntimeError("UE exited before its tunnel became ready")
            result = subprocess.run(
                DOCKER + ["exec", UE, "ip", "-j", "-4", "addr",
                          "show", "dev", "oaitun_ue1"],
                capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=10,
            )
            if result.returncode == 0:
                values = json.loads(result.stdout)
                ips = [
                    addr["local"] for item in values
                    for addr in item.get("addr_info", [])
                    if addr.get("family") == "inet"
                ]
                if len(ips) == 1:
                    ue_ip = ips[0]
                    break
            time.sleep(1)
        if not ue_ip:
            raise RuntimeError("UE tunnel readiness timeout")
        summary["ue_ip"] = ue_ip
        ran_before = {name: identity(name) for name in (GNB, UE)}
        ric_before = identity(temporary_ric)

        expected_gnb = json.loads(
            command(["image", "inspect", GNB_IMAGE]))[0]["Id"]
        if inspect(GNB)["Image"] != expected_gnb:
            raise RuntimeError("Unexpected gNB image")

        network = json.loads(command([
            "network", "inspect", "docker_open5gs_default",
        ]))[0]
        if any(
            item.get("IPv4Address", "").split("/")[0] == "172.22.0.151"
            for item in network.get("Containers", {}).values()
        ):
            raise RuntimeError("Traffic endpoint address is occupied")
        if "OAI_PI_TEST_REJECT_FIRST_DELETE=1" in (
            inspect(GNB)["Config"].get("Env") or []
        ):
            raise RuntimeError("Delete-rejection injection must be disabled")

        server = command([
            "create", "--pull", "never",
            "--name", "ocudu-csv-traffic-" + uuid.uuid4().hex[:12],
            "--network", "docker_open5gs_default", "--ip", "172.22.0.151",
            "--cap-add", "NET_ADMIN", "--entrypoint", "/bin/sh", SERVER_IMAGE,
            "-ec",
            "ip route add 192.168.100.0/24 via 172.22.0.8; "
            "exec timeout --signal=INT --kill-after=5s 240s "
            "iperf3 -s -B 172.22.0.151",
        ]).strip()
        command(["start", server])
        time.sleep(1)
        command([
            "exec", UE, "ping", "-I", "oaitun_ue1",
            "-c", "3", "-W", "2", "172.22.0.151",
        ], timeout=15)

        run_recovery(dest, ue_ip, summary)

        gnb_log = command(["logs", "--timestamps", GNB], timeout=120)
        # Retain runtime identities for independent mapping review.
        identity_lines = [
            line for line in gnb_log.splitlines()
            if "f1ap" in line.lower() or "ue=" in line.lower()
            or "rnti" in line.lower()
        ]
        (dest / "gnb-ue-identity.log").write_text("\n".join(identity_lines) + "\n")
        if "RICcontrolRequest" in gnb_log:
            raise RuntimeError("Unexpected gNB control request")
        if identity(temporary_ric) != ric_before:
            raise RuntimeError("Temporary RIC restarted or stopped")
        if {name: identity(name) for name in (GNB, UE)} != ran_before:
            raise RuntimeError("RAN process identity changed during probe")
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
    finally:
        # Collect diagnostics before stopping or recreating the test RAN.
        if ran_touched:
            try:
                log = command(["logs", "--timestamps", GNB], timeout=120)
                lines = [
                    line for line in log.splitlines()
                    if "[E2" in line or "assert" in line.lower()
                    or "subscription" in line.lower()
                ]
                (dest / "gnb-e2.log").write_text("\n".join(lines) + "\n")
                summary["ran_state_at_cleanup"] = {
                    name: identity(name) for name in (GNB, UE)
                }
            except Exception as error:
                summary.setdefault("diagnostic_errors", []).append(str(error))
        if temporary_ric:
            try:
                summary["test_ric_state_at_cleanup"] = identity(temporary_ric)
            except Exception as error:
                summary.setdefault("diagnostic_errors", []).append(str(error))
        if server:
            try:
                (dest / "traffic-server.log").write_text(
                    command(["logs", "--timestamps", server]))
            except Exception as error:
                summary.setdefault("diagnostic_errors", []).append(str(error))
            try:
                command(["rm", "-f", server])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if probe:
            try:
                command(["rm", "-f", probe])
                if attached is not None:
                    attached.wait(timeout=15)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if ran_touched:
            try:
                command(compose + ["--profile", "ue", "stop", "nrue", "gnb"],
                        timeout=90)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if temporary_ric:
            try:
                (dest / "ric.log").write_text(
                    command(["logs", "--timestamps", temporary_ric]))
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
            try:
                command(["rm", "-f", temporary_ric])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if ran_touched:
            try:
                command(compose + [
                    "--profile", "ue", "up", "--no-start", "--no-deps",
                    "--force-recreate", "--no-build", "--pull", "never",
                    "gnb", "nrue",
                ], timeout=90)
                if any(inspect(name)["State"]["Running"] for name in (GNB, UE)):
                    raise RuntimeError("RAN should be stopped after restoration")
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if before_ric is not None:
            try:
                summary["baseline_ric_after"] = identity(BASE_RIC)
                if summary["baseline_ric_after"] != before_ric:
                    raise RuntimeError("Baseline RIC identity changed")
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if summary["cleanup_errors"]:
            summary["passed"] = False
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
        print(f"Evidence retained: {dest}", flush=True)
    if not summary["passed"]:
        raise SystemExit(1)
    print("PASS: managed SDK reconnection, persistent QoS state, STALE and fresh alert/recovery.")
    print("Baseline RIC retained; original RAN configuration restored, stopped.")


if __name__ == "__main__":
    main()
