#!/usr/bin/env python3
"""One laboratory RC handover with separate ACK and execution checks."""
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import time
import uuid

from qos_startup_guard import wait_host_ready
from rc_handover_identity import extract_identity
CONTROL_IMAGE_IDS = {'ric': 'sha256:18358f2f935e9d3937a1469985b2c10427e170b6f0fa09a7dabfad1fdbb71977', 'handover-control': 'sha256:a9c7e2add4458b7fbb0b8b15ef371f7fc8a28c46ffe893d7f7078f82a9647a86'}

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ["sudo", "docker"]
BASE_RIC = "oai-pi-ocudu-zmq-lab-ric-1"
CORE = ("ausf", "udm", "udr", "nrf", "scp", "amf", "smf", "upf")
BRIDGE_ID = 'sha256:e81707f75606c8a64105ef9c4c27c8fefda67db8f676a304cb59cfd69bc130e2'


def progress(message):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
          + " [PROGRESS] " + message, flush=True)


_debug_seen = 0

def show_ue_debug(log):
    global _debug_seen
    lines = log.splitlines()
    selected = re.compile(
        r"LAB_HO_|LAB_GDB_|"
        r"Initial sync successful|Initial sync: pbch|"
        r"Processing reconfigurationWithSync|"
        r"4-Step RA procedure succeeded|"
        r"received signal|Program terminated|"
        r"^Thread \d+|^#\d+\s|"
        r"ptrace|Operation not permitted|"
        r"No debugging symbols|Cannot execute",
        re.I,
    )
    for line in lines[_debug_seen:]:
        # Strip Docker timestamps and terminal color escapes for matching.
        clean = re.sub(r"^\d{4}-\d\d-\d\dT\S+\s+", "", line)
        clean = re.sub(r"\x1b\[[0-9;]*m", "", clean)
        if selected.search(clean):
            print("[UE DEBUG] " + clean, flush=True)
    _debug_seen = len(lines)


def require(value, message):
    if not value:
        raise RuntimeError(message)

def command(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    require(result.returncode == 0,
            result.stderr.strip() or "Docker command failed")
    return result.stdout + result.stderr if args[0] == "logs" else result.stdout

def identity(name):
    item = json.loads(command(["inspect", name]))[0]
    return {
        "id": item["Id"], "image": item["Image"],
        "pid": item["State"]["Pid"],
        "started": item["State"]["StartedAt"],
        "restarts": item["RestartCount"],
        "running": item["State"]["Running"],
        "oom_killed": item["State"].get("OOMKilled", False),
    }


def handover_evidence(gnb_delta, ue_delta):
    finish_pattern = (
        r'ue=(\d+): "Intra CU Handover Target Routine" finished successfully'
    )
    finished = list(re.finditer(finish_pattern, gnb_delta))
    if len(finished) != 1:
        return False
    target_ue = finished[0].group(1)
    received = re.search(
        r'\bue=' + re.escape(target_ue)
        + r'\s+c-rnti=0x[0-9a-fA-F]+: DCCH UL rrcReconfigurationComplete\b',
        gnb_delta,
    )
    if not received or received.end() > finished[0].start():
        return False

    position = 0
    for pattern in (
        r"Processing reconfigurationWithSync",
        r"Initial sync successful, PCI:\s*2\b",
        r"4-Step RA procedure succeeded",
    ):
        match = re.search(pattern, ue_delta[position:])
        if not match:
            return False
        position += match.end()
    return True


def main():
    os.umask(0o077)
    parent = ROOT / "test/ocudu/.local/evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-rc-handover-dockerhub-", dir=parent))
    print("Evidence:", dest, flush=True)
    summary = {
        "passed": False, "cleanup_errors": [],
        "scope": "One RC handover from PCI 1 to PCI 2 over laboratory IQ bridge",
        "radio_frame_alignment_validated": False,
        "control_ack_validated": False,
        "handover_execution_validated": False,
        "control_requests_sent": 0,
    }
    compose = None
    touched = False
    core_before = baseline = None
    containers = {}
    project = "ocudu-rc-" + uuid.uuid4().hex[:12]

    with tempfile.TemporaryDirectory(prefix="private-", dir=dest) as tmp:
        private = Path(tmp)
        try:
            for name in ("oai-pi-ocudu-zmq-lab-gnb-1",
                         "oai-pi-ocudu-zmq-lab-nrue-1"):
                require(not command([
                    "ps", "-q", "--filter", "name=^/" + name + "$",
                ]).strip(), "Original test RAN is running")

            core_before = {name: identity(name) for name in CORE}
            baseline = identity(BASE_RIC)
            summary["core_before"] = core_before
            summary["baseline_ric_before"] = baseline
            require(all(x["running"] and not x["oom_killed"]
                        for x in core_before.values()), "Core unhealthy")
            require(baseline["running"], "Baseline RIC must remain running")

            network = json.loads(command([
                "network", "inspect", "docker_open5gs_default",
            ]))[0]
            occupied = {
                x.get("IPv4Address", "").split("/")[0]
                for x in network.get("Containers", {}).values()
            }
            require(not occupied.intersection({
                "172.22.0.160", "172.22.0.161", "172.22.0.163",
            }), "Required test address occupied")

            prepare = runpy.run_path(str(
                ROOT / "test/ocudu/prepare-rc-two-cell-fallback-dci-v2.py"
            ))["prepare"]
            config = private / "config"
            summary["configuration"] = prepare(ROOT, config)
            env = private / "compose.env"
            env.write_text(
                f"OCUDU_DUAL_CONFIG={config}\n"
                f"OCUDU_RC_CONFIG={config}\n"
                f"OCUDU_RC_EVIDENCE={dest}\n"
            )
            compose = [
                "compose", "--project-name", project,
                "--env-file", str(env),
                "-f", str(ROOT / "deploy/ocudu/compose.rc-two-cell-source-mute.yaml"),
                "-f", str(ROOT / "deploy/ocudu/compose.rc-handover-control.yaml"),
                "-f", str(ROOT / "deploy/ocudu/compose.rc-handover-dockerhub.yaml"),
                "--profile", "ue",
            ]
            resolved = json.loads(command(compose + ["config", "--format", "json"]))
            services = resolved["services"]
            require(set(services) == {"ric", "gnb", "nrue", "iq-bridge", "handover-control"},
                    "Unexpected Compose services")
            summary["images"] = {}
            for name, service in services.items():
                require(service.get("pull_policy") == "never",
                        "Unexpected pull policy")
                image = json.loads(command([
                    "image", "inspect", service["image"],
                ]))[0]
                require(image["Os"] == "linux" and image["Architecture"] == "arm64",
                        "Unexpected image platform")
                summary["images"][name] = image["Id"]
            require(summary["images"]["iq-bridge"] == BRIDGE_ID,
                    "Bridge image differs from checked image")

            require(summary["images"]["nrue"] == 'sha256:bbdceed41714844717eaf9a06e09284f5404e27daff870d1f1ec08c782182047',
                    "Configuration-selection UE image differs from pinned image")
            for name, expected in CONTROL_IMAGE_IDS.items():
                require(summary["images"][name] == expected,
                        "Control image differs from pinned image: " + name)
            progress('Checking host readiness')
            summary["host_readiness"] = wait_host_ready(dest / "host-readiness.json")
            touched = True
            for service in ("ric", "iq-bridge", "gnb", "nrue"):
                progress("Starting service: " + service)
                command(compose + [
                    "up", "-d", "--no-deps", "--no-build",
                    "--pull", "never", service,
                ], timeout=90)
                cid = command(compose + ["ps", "--all", "-q", service]).strip()
                require(cid and len(cid.splitlines()) == 1,
                        "Expected one test container")
                containers[service] = cid
                time.sleep(2)

            deadline = time.monotonic() + 120
            address = None
            while time.monotonic() < deadline:
                require(all(identity(cid)["running"] for cid in containers.values()),
                        "A test service exited during UE startup")
                result = subprocess.run(
                    DOCKER + ["exec", containers["nrue"], "ip", "-j", "-4",
                              "addr", "show", "dev", "oaitun_ue1"],
                    capture_output=True, text=True, timeout=12,
                    stdin=subprocess.DEVNULL,
                )
                if result.returncode == 0:
                    addresses = [
                        a["local"] for item in json.loads(result.stdout)
                        for a in item.get("addr_info", [])
                        if a.get("family") == "inet"
                    ]
                    if len(addresses) == 1:
                        address = addresses[0]
                        break
                time.sleep(1)
            require(address, "UE tunnel readiness timeout")
            summary["ue_address"] = address
            before = {name: identity(cid) for name, cid in containers.items()}
            require(all(x["running"] and not x["oom_killed"]
                        for x in before.values()), "Test process unhealthy")
            for name, state in before.items():
                require(state["image"] == summary["images"][name],
                        "Unexpected running image")

            for probe in range(1, 6):
                result = subprocess.run(
                    DOCKER + ["exec", containers["nrue"], "ping", "-n", "-D",
                              "-I", "oaitun_ue1", "-c", "1", "-W", "3",
                              "192.168.100.1"],
                    capture_output=True, text=True, timeout=10,
                    stdin=subprocess.DEVNULL,
                )
                output = result.stdout + result.stderr
                (dest / f"ping-{probe}.log").write_text(output)
                require(result.returncode == 0
                        and "1 packets transmitted, 1 received" in output
                        and " 0% packet loss" in output, "UPF ping failed")
                time.sleep(1)

            cfg = summary["configuration"]
            require(
                cfg["cu_cp_e2_enabled"] is True
                and cfg["du_e2_enabled"] is False
                and cfg["cu_up_e2_enabled"] is False
                and cfg["rc_enabled"] is True
                and cfg["kpm_enabled"] is False,
                "Unexpected E2 role configuration",
            )
            gnb_log = command(["logs", containers["gnb"]], timeout=60)
            e2_lines = [
                line for line in gnb_log.splitlines()
                if "[E2-CU-CP]" in line
            ]
            require(any("E2 Setup procedure successful." in line
                        for line in e2_lines),
                    "CU-CP E2 Setup success evidence missing")
            require(any(
                "Added supported RAN function with id 3" in line
                and "1.3.6.1.4.1.53148.1.1.2.3" in line
                for line in e2_lines
            ), "CU-CP RC function evidence missing")
            require(not any(
                "[E2-DU]" in line or "[E2-CU-UP]" in line
                for line in gnb_log.splitlines()
            ), "Unexpected additional E2 agent log")
            summary["cu_cp_identity_acceptance"] = {
                "validated": True,
                "basis": "CU-CP-only configuration and E2-CU-CP setup/function logs",
                "control_style_action_validated": False,
            }
            cell_evidence = {}
            for pci in (1, 2):
                pattern = re.compile(r"\bpci\s*[=:]\s*" + str(pci) + r"\b", re.I)
                lines = [line for line in gnb_log.splitlines() if pattern.search(line)]
                require(lines, "Missing gNB log evidence for PCI " + str(pci))
                cell_evidence[str(pci)] = lines[:5]
            summary["cell_log_evidence"] = cell_evidence
            require("RICcontrolRequest" not in gnb_log
                    and "Received RIC Control Request" not in gnb_log,
                    "Unexpected control request")
            summary["connectivity_acceptance"] = {
                "validated": True,
                "basis": "Two configured PCIs logged; UE tunnel and five UPF pings",
                "handover_validated": False,
                "radio_frame_alignment_validated": False,
            }
            require({name: identity(containers[name]) for name in before} == before,
                    "Test process identity changed")

            ric_log = command(["logs", containers["ric"]], timeout=60)
            (dest / "ric-capability.log").write_text(ric_log)
            accepted = [int(x) for x in re.findall(
                r"Accepting RAN function ID (\d+)", ric_log)]
            require(3 in accepted, "RIC acceptance evidence for RC missing")
            summary["ric_accepted_function_ids"] = accepted

            progress('UE connectivity checks passed; extracting current-run identity')
            ue_before = command(["logs", containers["nrue"]], timeout=30)
            live = extract_identity(gnb_log, ue_before)
            summary["source_identity"] = live
            (dest / "source-identity.json").write_text(
                json.dumps(live, indent=2) + "\n")
            (dest / "gnb.before-control.log").write_text(gnb_log)
            (dest / "nrue.before-control.log").write_text(ue_before)
            variables = {
                "RC_RAN_UE_ID": live["ran_ue_id"],
                "RC_AMF_UE_ID": live["amf_ue_id"],
                "RC_CU_F1AP_ID": live["cu_f1ap_id"],
                "RC_AMF_REGION": live["amf_region"],
                "RC_AMF_SET": live["amf_set"],
                "RC_AMF_POINTER": live["amf_pointer"],
            }
            with env.open("a") as stream:
                for key, value in variables.items():
                    stream.write(f"{key}={value}\n")
            updated = json.loads(command(compose + ["config", "--format", "json"]))
            settings = updated["services"]["handover-control"]["environment"]
            for key, value in variables.items():
                require(str(settings["XAPP_" + key[3:]]) == str(value),
                        "Resolved live identity differs: " + key)
            require(settings["XAPP_TARGET_CGI_HEX"] == live["target_cgi_hex"]
                    and str(settings["XAPP_SOURCE_NR_CGI"]) == "107520"
                    and str(settings["XAPP_TARGET_NR_CGI"]) == "107521",
                    "Unexpected source or target CGI")
            command(compose + [
                "create", "--no-build", "--pull", "never", "handover-control",
            ], timeout=60)
            cid = command(compose + [
                "ps", "--all", "-q", "handover-control",
            ]).strip()
            require(cid and len(cid.splitlines()) == 1, "Expected one control xApp")
            containers["handover-control"] = cid
            require(identity(cid)["image"] == CONTROL_IMAGE_IDS["handover-control"],
                    "Unexpected control container image")
            progress('Starting the one-shot control xApp; its output is retained in probe.stdout')
            with (dest / "probe.stdout").open("x") as out, \
                 (dest / "probe.stderr").open("x") as err:
                result = subprocess.run(
                    DOCKER + ["start", "-a", cid], stdout=out, stderr=err,
                    stdin=subprocess.DEVNULL, timeout=65,
                )
            probe_log = (dest / "probe.stdout").read_text()
            probe_err = (dest / "probe.stderr").read_text()
            summary["control_requests_sent"] = len(re.findall(
                r"\bLAB_RC_REQUEST\b", probe_log))
            require(result.returncode == 0, "Handover xApp failed")
            state = json.loads(command(["inspect", cid]))[0]["State"]
            require(not state["Running"] and state["ExitCode"] == 0,
                    "Control xApp did not exit successfully")
            ric_after = command(["logs", containers["ric"]], timeout=30)

            def event(log, marker):
                records = [
                    {key: int(value) for key, value in
                     re.findall(r"(\w+)=(\d+)", line)}
                    for line in log.splitlines()
                    if re.search(r"\b" + re.escape(marker) + r"\b", line)
                ]
                require(len(records) == 1, "Expected one " + marker)
                return records[0]

            request = event(probe_log, "LAB_RC_REQUEST")
            mapping = event(ric_after, "LAB_RC_MAP")
            ack = event(ric_after, "LAB_RC_ACK_RIC")
            forwarded = event(ric_after, "LAB_RC_ACK_FORWARD")
            received = event(probe_log, "LAB_RC_ACK_XAPP")
            require(request["node"] == mapping["node"] == 420,
                    "Unexpected control node")
            require(request["request"] == mapping["xapp_request"]
                    == forwarded["xapp_request"] == received["request"],
                    "xApp request correlation failed")
            require(mapping["ric_request"] == ack["request"]
                    == forwarded["ric_request"], "RIC request correlation failed")
            require(mapping["xapp"] == forwarded["xapp"], "Recipient mismatch")
            for record in (request, mapping, ack, forwarded, received):
                require(record["function"] == 3
                        and record["instance"] == request["instance"],
                        "Control identity mismatch")
            require(probe_log.count("LAB_RC_POSITIVE_API_ACK") == 1,
                    "API ACK evidence missing")
            combined = probe_log + probe_err + ric_after
            require(not any(marker in combined for marker in (
                "LAB_RC_FAILURE_", "LAB_RC_IGNORED_", "LAB_RC_UNMAPPED_",
                "LAB_RC_POSITIVE_API_FAILED", "Assertion",
            )), "Unexpected control failure or unmatched response")
            progress('Control ACK correlation passed')
            summary["control_ack_validated"] = True
            summary["control_correlation"] = {
                "request": request, "mapping": mapping,
                "ric_ack": ack, "forwarded_ack": forwarded, "xapp_ack": received,
            }

            # Mute only after ACK validation and current-run UE reception.
            mute_deadline = time.monotonic() + 10
            while True:
                observed = command(["logs", containers["nrue"]], timeout=10)
                require(observed.startswith(ue_before),
                        "UE log prefix changed before source mute")
                delta = observed[len(ue_before):]
                if "Processing reconfigurationWithSync" in delta:
                    break
                require(time.monotonic() < mute_deadline,
                        "UE did not confirm reception before source mute")
                time.sleep(0.2)
            (dest / "nrue.before-source-mute.log").write_text(observed)
            progress('UE received the handover command; requesting source mute')
            command(["kill", "--signal", "USR1", containers["iq-bridge"]],
                    timeout=10)
            mute_deadline = time.monotonic() + 5
            while True:
                bridge_log = command(["logs", containers["iq-bridge"]],
                                     timeout=10)
                records = []
                for line in bridge_log.splitlines():
                    if '"LAB_SOURCE_MUTED"' in line:
                        records.append(json.loads(line))
                if records:
                    break
                require(time.monotonic() < mute_deadline,
                        "Bridge source mute confirmation missing")
                time.sleep(0.2)
            require(len(records) == 1
                    and records[0].get("gains") == [0.0, 0.45],
                    "Unexpected source mute confirmation")
            progress('Bridge confirmed source mute; target gain remains 0.45')
            summary["source_mute"] = {
                "trigger": "ACK validated and UE reconfigurationWithSync observed",
                "event": records[0],
            }
            (dest / "bridge.source-mute.log").write_text(bridge_log)

            deadline = time.monotonic() + 30
            completed = []
            while time.monotonic() < deadline:
                require(all(identity(containers[name])["running"] for name in before),
                        "A RAN or bridge service exited")
                gnb_after = command(["logs", containers["gnb"]], timeout=30)
                ue_after = command(["logs", containers["nrue"]], timeout=30)
                require(gnb_after.startswith(gnb_log) and ue_after.startswith(ue_before),
                        "Runtime log history changed")
                gnb_delta = gnb_after[len(gnb_log):]
                ue_delta = ue_after[len(ue_before):]
                show_ue_debug(ue_after)
                completed = re.findall(
                    r'ue=(\d+): "Intra CU Handover Target Routine" finished successfully',
                    gnb_delta,
                )
                if handover_evidence(gnb_delta, ue_delta):
                    break
                time.sleep(1)
            (dest / "gnb.after-control.log").write_text(gnb_after)
            (dest / "nrue.after-control.log").write_text(ue_after)
            require(len(completed) == 1, "Target handover completion missing or duplicated")
            require(handover_evidence(gnb_delta, ue_delta),
                    "Correlated target handover evidence missing")
            require(len(re.findall(r"Received RIC Control Request", gnb_delta)) == 1,
                    "Expected one gNB control request")
            require(re.search(
                r"Executing E2SM-RC Handover Request Trigger intra-CU \(intra-DU\)"
                r" handover for ue=" + str(live["ue_index"]) + r"\b", gnb_delta),
                "Source UE handover trigger missing")
            summary["handover_execution_validated"] = True
            summary["handover_acceptance"] = {
                "source_pci": 1, "target_pci": 2,
                "source_nci": 107520, "target_nci": 107521,
                "target_ue_index": int(completed[0]),
                "basis": "UE command, PCI 2 synchronization and RA; target UE RRC complete and routine success",
            }
            for probe in range(1, 6):
                result = subprocess.run(
                    DOCKER + ["exec", containers["nrue"], "ping", "-n", "-D",
                              "-I", "oaitun_ue1", "-c", "1", "-W", "3",
                              "192.168.100.1"],
                    capture_output=True, text=True, timeout=10,
                    stdin=subprocess.DEVNULL,
                )
                output = result.stdout + result.stderr
                (dest / f"ping-after-control-{probe}.log").write_text(output)
                require(result.returncode == 0
                        and "1 packets transmitted, 1 received" in output
                        and " 0% packet loss" in output,
                        "Post-handover UPF ping failed")
                time.sleep(1)
            summary["post_handover_pings_passed"] = 5
            require({name: identity(containers[name]) for name in before} == before,
                    "Test process identity changed after control")

            progress('All existing handover acceptance checks passed')
            summary["passed"] = True
        except Exception as error:
            summary["error"] = str(error)
            progress("Validation stopped: " + str(error))
        finally:
            progress('Collecting evidence and cleaning up test containers')
            if touched and compose:
                try:
                    for service in ("ric", "gnb", "nrue", "iq-bridge", "handover-control"):
                        cid = command(compose + [
                            "ps", "--all", "-q", service,
                        ]).strip()
                        if cid and len(cid.splitlines()) == 1:
                            runtime_log = command(
                                ["logs", "--timestamps", cid], timeout=60)
                            (dest / f"{service}.runtime-private.log").write_text(
                                runtime_log)
                            if service == "nrue":
                                show_ue_debug(runtime_log)
                except Exception as error:
                    summary["diagnostic_error"] = str(error)
                try:
                    command(compose + ["down", "--timeout", "15"], timeout=120)
                    remaining = command([
                        "ps", "-aq", "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]).strip()
                    require(not remaining, "Test containers remain")
                except Exception as error:
                    summary["cleanup_errors"].append(str(error))
            for key, previous, current in (
                ("core", core_before, lambda: {name: identity(name) for name in CORE}),
                ("baseline_ric", baseline, lambda: identity(BASE_RIC)),
            ):
                if previous is not None:
                    try:
                        value = current()
                        summary[key + "_after"] = value
                        require(value == previous, key + " identity changed")
                    except Exception as error:
                        summary["cleanup_errors"].append(str(error))
            if summary["cleanup_errors"]:
                summary["passed"] = False
            (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps(summary, indent=2), flush=True)

    if not summary["passed"]:
        raise SystemExit(1)
    print("PASS: one correlated RC ACK, target handover completion, UE PCI transition and five post-handover pings.")

if __name__ == "__main__":
    main()
