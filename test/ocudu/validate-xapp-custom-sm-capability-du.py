#!/usr/bin/env python3
"""Audit OCUDU DU custom-SM advertised capability through Compose."""

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
from qos_startup_guard import wait_host_ready
import re
import hashlib

METRICS = {'RRU.PrbAvailDl': ('PRB', 'scheduler', 'cell_available_prbs'), 'RRU.PrbAvailUl': ('PRB', 'scheduler', 'cell_available_prbs'), 'RRU.PrbUsedDl': ('PRB', 'scheduler', 'integer_mean_prbs_per_dl_slot'), 'RRU.PrbUsedUl': ('PRB', 'scheduler', 'integer_mean_prbs_per_ul_slot'), 'RRU.PrbTotDl': ('percent', 'scheduler', 'integer_prb_utilization'), 'RRU.PrbTotUl': ('percent', 'scheduler', 'integer_prb_utilization'), 'DRB.RlcSduTransmittedVolumeDL': ('kbit', 'RLC', 'cached_sdu_batch_volume'), 'DRB.RlcSduTransmittedVolumeUL': ('kbit', 'RLC', 'cached_sdu_batch_volume'), 'DRB.UEThpDl': ('kbps', 'RLC', 'provider_mean_throughput'), 'DRB.UEThpUl': ('kbps', 'RLC', 'provider_mean_throughput')}

DOCKER = ["sudo", "docker"]
GNB = "oai-pi-ocudu-zmq-lab-gnb-1"
UE = "oai-pi-ocudu-zmq-lab-nrue-1"
BASE_RIC = "oai-pi-ocudu-zmq-lab-ric-1"
RIC_IMAGE = "limx59/oai-pi-ocudu-flexric-ric:arm64-kpm-csv-metadata-test"
XAPP_IMAGE = "limx59/oai-pi-ocudu-flexric-xapp:arm64-custom-sm-capability-test@sha256:2c3add43804b9494a9d84037980c8dc2d48285214559d277e1d38ec4a6ee2e03"
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





def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-custom-sm-capability-du-", dir=parent))
    print(f"Evidence: {dest}", flush=True)
    summary = {
        "passed": False,
        "scope": "OCUDU DU advertised custom-SM compatibility boundary",
        "limitations": "Single laboratory DU; advertised capability only; no custom subscriptions or delivery validation",
        "capability_criteria": {"expected_functions": [2], "custom_ids": [142, 143, 144]},
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

        summary["host_readiness"] = wait_host_ready(
            dest / "host-readiness.json")
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
            "exec timeout --signal=INT --kill-after=5s 180s "
            "iperf3 -s -B 172.22.0.151",
        ]).strip()
        command(["start", server])
        time.sleep(1)
        command([
            "exec", UE, "ping", "-I", "oaitun_ue1",
            "-c", "3", "-W", "2", "172.22.0.151",
        ], timeout=15)

        project = "ocudu-compat-" + uuid.uuid4().hex[:12]
        env_file = dest / "compose-probe.env"
        env_file.write_text(
            f"OCUDU_CAPABILITY_EVIDENCE={dest}\n"
            f"OCUDU_CAPABILITY_IMAGE={XAPP_IMAGE}\n"
            "OCUDU_CAPABILITY_ROLE=ngran_gNB_DU\n"
        )
        probe_compose = [
            "compose", "--project-name", project,
            "--env-file", str(env_file),
            "-f", str(root / "deploy/ocudu/compose.xapp-custom-sm-capability.yaml"),
        ]
        merged = command(probe_compose + ["config", "--format", "json"])
        (dest / "compose-probe.resolved.json").write_text(merged)
        config = json.loads(merged)
        service = config["services"]["custom-sm-capability"]
        if service["image"] != XAPP_IMAGE:
            raise RuntimeError("Unexpected Compose xApp image")
        command(probe_compose + [
            "create", "--no-build", "--pull", "never", "custom-sm-capability",
        ], timeout=60)
        probe = command(probe_compose + [
            "ps", "--all", "--quiet", "custom-sm-capability",
        ]).strip()
        if not probe or len(probe.splitlines()) != 1:
            raise RuntimeError("Expected one Compose probe container")
        if inspect(probe)["Image"] != summary["images"][XAPP_IMAGE]:
            raise RuntimeError("Compose probe uses an unexpected image")
        summary["probe_launch"] = {
            "method": "docker compose create; docker start -a",
            "project": project,
            "compose_file": "deploy/ocudu/compose.xapp-custom-sm-capability.yaml",
            "image": XAPP_IMAGE,
            "image_id": inspect(probe)["Image"],
        }
        with (dest / "probe.stdout").open("w") as out, \
             (dest / "probe.stderr").open("w") as err:
            attached = subprocess.Popen(
                DOCKER + ["start", "-a", probe],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            )
            attached.wait(timeout=55)
            if attached.returncode:
                raise RuntimeError("Original demo failed; inspect probe logs")

        state = inspect(probe)["State"]
        if state["Running"] or state["ExitCode"]:
            raise RuntimeError("Original demo did not exit successfully")
        capability = json.loads((dest / "capability.json").read_text())
        if not capability["passed"] or capability["cleanup_errors"]:
            raise RuntimeError("Capability probe failed")
        if (capability["node_id"], capability["role"]) != (420, "ngran_gNB_DU"):
            raise RuntimeError("Unexpected capability target")
        functions = capability["advertised_functions"]
        if len(functions) != 1 or functions[0]["id"] != 2:
            raise RuntimeError("Capability differs from expected KPM-only boundary")
        if capability["subscription_attempts"] != 0:
            raise RuntimeError("Discovery probe attempted a subscription")
        for name, function_id in (("MAC", 142), ("RLC", 143), ("PDCP", 144)):
            item = capability["custom_models"][name]
            if (item["ran_function_id"] != function_id or item["advertised"]
                    or item["delivery_validated"]
                    or item["decision"] != "unsupported_not_advertised"):
                raise RuntimeError("Incorrect custom-SM classification")
        stdout = (dest / "probe.stdout").read_text()
        stderr = (dest / "probe.stderr").read_text()
        ric_log = command(["logs", "--timestamps", temporary_ric])
        (dest / "capability-ric.log").write_text(ric_log)
        accepted = [
            int(value) for value in re.findall(
                r"Accepting RAN function ID (\d+)", ric_log)
        ]
        if accepted != [2]:
            raise RuntimeError("RIC accepted-function evidence mismatch")
        for log in (stdout, stderr, ric_log):
            if re.search(r"SUBSCRIPTION[-_ ]REQUEST", log, re.I):
                raise RuntimeError("Unexpected subscription request in discovery run")
            if re.search(r"Traceback|Assertion", log, re.I):
                raise RuntimeError("Capability run contains process failure markers")
        summary["capability"] = capability
        summary["ric_accepted_function_ids"] = accepted
        gnb_log = command(["logs", "--timestamps", GNB], timeout=120)
        # Retain runtime identities for independent mapping review.
        identity_lines = [
            line for line in gnb_log.splitlines()
            if "f1ap" in line.lower() or "ue=" in line.lower()
            or "rnti" in line.lower()
        ]
        (dest / "gnb-ue-identity.log").write_text("\n".join(identity_lines) + "\n")
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
    print("PASS: DU custom-SM unsupported boundary audited; no subscriptions sent.")
    print("Baseline RIC retained; original RAN configuration restored, stopped.")


if __name__ == "__main__":
    main()
