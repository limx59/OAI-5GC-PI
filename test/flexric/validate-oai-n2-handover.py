#!/usr/bin/env python3
"""Validate one experimental E2 RC-triggered N2 handover."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-n2-handover-auto"))
    parser.add_argument("--xapp-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-ue-context-test")
    parser.add_argument("--compose-overlay", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence: {output}", flush=True)
    root = Path(__file__).resolve().parents[2]
    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    for filename in (
        "compose.oai.yaml", "compose.oai-radio-stats.yaml",
        "compose.oai-n2-handover.yaml", "compose.oai-rc-sdk.yaml",
    ):
        compose += ["-f", str(root / "deploy/oai-flexric" / filename)]
    if args.compose_overlay is not None:
        overlay = args.compose_overlay.resolve(strict=True)
        compose += ["-f", str(overlay)]
        summary_overlay = str(overlay)
    else:
        summary_overlay = None
    names = [
        "oai-pi-oai-e2-lab-ric-1", "oai-pi-oai-e2-lab-gnb-1",
        "oai-pi-oai-e2-lab-gnb-2-1", "oai-pi-oai-e2-lab-nrue-1",
    ]
    temporary = set()
    summary = {"passed": False, "cleanup_errors": [],
               "compose_overlay": summary_overlay}

    def run(command, timeout=30):
        return subprocess.run(command, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    def checked(command, timeout=30):
        result = run(command, timeout)
        require(result.returncode == 0,
                f"Command failed: {command[:5]}: {result.stderr[-1000:]}")
        return result.stdout + result.stderr

    def inspect():
        items = json.loads(checked(docker + ["inspect", *names]))
        return {item["Name"].lstrip("/"): item for item in items}

    def identity(item):
        return {
            "id": item["Id"], "image": item["Image"],
            "pid": item["State"]["Pid"],
            "started_at": item["State"]["StartedAt"],
            "restart_count": item["RestartCount"],
            "cpuset": item["HostConfig"]["CpusetCpus"],
        }

    def logs(name, since):
        return checked(docker + ["logs", "--timestamps", "--since", since, name])

    def wait_setup(name, markers, seconds=60):
        deadline = time.monotonic() + seconds
        while True:
            item = json.loads(checked(docker + ["inspect", name]))[0]
            require(item["State"]["Running"], f"{name} stopped")
            text = logs(name, item["State"]["StartedAt"])
            if all(marker in text for marker in markers):
                return
            require(time.monotonic() < deadline, f"{name}: setup timeout")
            time.sleep(2)

    def ping(label):
        text = checked(docker + ["exec", names[3], "ping", "-I", "oaitun_ue1",
                                "-c", "5", "-W", "5", "192.168.100.1"], 40)
        (output / f"{label}.log").write_text(text)
        require("5 packets transmitted, 5 received, 0% packet loss" in text,
                f"{label}: packet loss")
        print(f"PASS: {label}, 5/5 replies", flush=True)

    def tun_address():
        text = checked(docker + ["exec", names[3], "ip", "-j", "-4",
                                "addr", "show", "dev", "oaitun_ue1"])
        addresses = [
            address["local"] for interface in json.loads(text)
            for address in interface.get("addr_info", [])
            if address.get("family") == "inet"
        ]
        require(len(addresses) == 1, "Expected one UE IPv4 address")
        return addresses[0]

    def xapp(label, control=False):
        name = "oai-n2-validator-" + uuid.uuid4().hex[:10]
        temporary.add(name)
        config = root / "deploy/oai-flexric/config/oai/xapp-oai-context.conf"
        command = docker + [
            "run", "--rm", "--name", name, "--network", "oai-pi-flexric-lab",
            "--mount",
            f"type=bind,src={config},dst=/usr/local/etc/flexric/xapp.conf,readonly",
        ]
        if control:
            command += ["-e", "OAI_N2_CONTROL_TEST=1"]
        command += [args.xapp_image, "-c", "/usr/local/etc/flexric/xapp.conf",
                    "-p", "/usr/local/lib/flexric/"]
        try:
            result = run(command, 45)
            text = result.stdout + result.stderr
        except subprocess.TimeoutExpired as error:
            def decode(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            (output / f"{label}.log").write_text(
                decode(error.stdout) + decode(error.stderr))
            raise
        (output / f"{label}.log").write_text(text)
        require(result.returncode == 0, f"{label}: xApp exit {result.returncode}")
        require("E42 SUBSCRIPTION DELETE RESPONSE rx" in text,
                f"{label}: subscription cleanup missing")
        require("RC context: UEs=1" in text and "cell=12345678" in text
                and "Neighbour:" in text and "cell=720898" in text,
                f"{label}: unexpected context")
        if control:
            require("CONTROL ACK rx" in text and "Control submitted;" in text,
                    "Control acknowledgement missing")
        print(f"PASS: {label}", flush=True)

    try:
        # Reset only the dedicated OAI experiment; core and host are retained.
        checked(compose + ["--profile", "ue", "stop", "--timeout", "15",
                           "nrue", "gnb", "gnb-2"], 60)
        checked(compose + ["up", "-d", "--no-build", "--pull", "never",
                           "--no-deps", "--force-recreate", "ric"], 45)
        checked(compose + ["up", "-d", "--no-build", "--pull", "never",
                           "--no-deps", "--force-recreate", "gnb"], 45)
        wait_setup(names[1], ["Received NGSetupResponse", "F1 Setup Response",
                              "E2 SETUP RESPONSE rx"])
        checked(compose + ["--profile", "ue", "up", "-d", "--no-build",
                           "--pull", "never", "--no-deps",
                           "--force-recreate", "nrue"], 45)
        wait_setup(names[3], ["PDU Session Establishment Accept",
                              "TUN Interface"], 120)
        ping("baseline-single-cell")
        checked(compose + ["up", "-d", "--no-build", "--pull", "never",
                           "--no-deps", "--force-recreate", "gnb-2"], 45)
        wait_setup(names[2], ["Received NGSetupResponse", "F1 Setup Response",
                              "E2 SETUP RESPONSE rx"])
        xapp("baseline-context")
        ping("baseline-two-cells")
        before = inspect()
        require(all(item["State"]["Running"] for item in before.values()),
                "Baseline process stopped")
        saved = {name: identity(item) for name, item in before.items()}
        ue_ip = tun_address()
        requested = datetime.now(timezone.utc).isoformat()
        (output / "before.json").write_text(json.dumps({
            "requested_at": requested, "processes": saved, "ue_ip": ue_ip,
        }, indent=2) + "\n")
        xapp("control", True)
        deadline = time.monotonic() + 60
        while True:
            items = inspect()
            for name, item in items.items():
                require(item["State"]["Running"] and identity(item) == saved[name],
                        f"{name}: process changed or stopped")
            text = logs(names[2], requested)
            if re.search(r"handover for UE .* complete!", text) and "Handover Notify" in text:
                break
            require(time.monotonic() < deadline, "Target handover completion timeout")
            time.sleep(2)
        for name in names:
            text = logs(name, requested)
            selected = [line for line in text.splitlines() if any(
                marker in line.lower() for marker in (
                    "handover", "reconfiguration", "initial sync",
                    "bearer release complete", "assertion",
                ))]
            (output / f"{name}-events.log").write_text("\n".join(selected) + "\n")
        stats_code = (
            "from pathlib import Path; "
            "print(Path('/opt/oai-gnb/bin/nrRRC_stats.log').read_text())"
        )
        deadline = time.monotonic() + 30
        while True:
            source = checked(docker + ["exec", names[1], "python3", "-c", stats_code])
            target = checked(docker + ["exec", names[2], "python3", "-c", stats_code])
            if ("PDU session ID 1 status established" in target
                    and "nrCellID 720898, PCI 1" in target
                    and "CU UE ID" not in source):
                break
            require(time.monotonic() < deadline, "RRC post-handover state timeout")
            time.sleep(2)
        (output / "source-rrc.log").write_text(source)
        (output / "target-rrc.log").write_text(target)
        require(tun_address() == ue_ip, "UE IP changed")
        ping("after-handover")
        final = inspect()
        require(all(item["State"]["Running"] and identity(item) == saved[name]
                    for name, item in final.items()), "Final process identity failure")
        summary.update({
            "passed": True, "all_four_processes_unchanged": True,
            "target_handover_complete_and_notify": True,
            "target_pdu_session_established": True, "source_ue_removed": True,
            "ue_ip_unchanged": True, "ue_ip": ue_ip,
            "post_handover_ping_received": 5,
            "limitations": [
                "No interruption-time measurement or load-driven policy.",
                "One forward N2 handover; reverse mobility is unvalidated.",
                "Fresh context subscriptions; production availability is unvalidated.",
            ],
        })
        print("PASS: N2 handover, session, IP, traffic and process checks", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        for name in temporary:
            result = run(docker + ["rm", "-f", name], 15)
            if result.returncode and "No such container" not in result.stderr:
                summary["cleanup_errors"].append(result.stderr)
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)

if __name__ == "__main__":
    main()
