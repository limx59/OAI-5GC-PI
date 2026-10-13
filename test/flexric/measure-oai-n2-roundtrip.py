#!/usr/bin/env python3
"""Measure ICMP reachability during an experimental N2 round trip."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-n2-roundtrip-measurement"))
    parser.add_argument("--xapp-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-n2-bidirectional-test")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence: {output}", flush=True)
    root = Path(__file__).resolve().parents[2]
    docker = ["sudo", "docker"]
    names = [
        "oai-pi-oai-e2-lab-ric-1", "oai-pi-oai-e2-lab-gnb-1",
        "oai-pi-oai-e2-lab-gnb-2-1", "oai-pi-oai-e2-lab-nrue-1",
    ]
    summary = {"passed": False, "directions": [], "cleanup_errors": []}
    monitor = None
    temporary = set()

    def run(command, timeout=20):
        result = subprocess.run(command, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr[-1000:] or f"Exit {result.returncode}")
        return result.stdout + result.stderr

    def identities():
        records = json.loads(run(docker + ["inspect", *names]))
        result = {}
        for item in records:
            if not item["State"]["Running"]:
                raise RuntimeError(f"{item['Name']} stopped")
            result[item["Name"]] = [
                item["Id"], item["Image"], item["State"]["Pid"],
                item["State"]["StartedAt"], item["RestartCount"],
                item["HostConfig"]["CpusetCpus"],
            ]
        return result

    def address():
        items = json.loads(run(docker + [
            "exec", names[3], "ip", "-j", "-4", "addr", "show", "dev", "oaitun_ue1"]))
        return [a["local"] for item in items for a in item.get("addr_info", [])
                if a.get("family") == "inet"]

    def context(direction, control=False):
        name = "oai-n2-measure-" + uuid.uuid4().hex[:10]
        temporary.add(name)
        config = root / "deploy/oai-flexric/config/oai/xapp-oai-context.conf"
        command = docker + [
            "run", "--rm", "--name", name, "--network", "oai-pi-flexric-lab",
            "-e", f"OAI_N2_DIRECTION={direction}",
            "--mount",
            f"type=bind,src={config},dst=/usr/local/etc/flexric/xapp.conf,readonly",
        ]
        if control:
            command += ["-e", "OAI_N2_CONTROL_TEST=1"]
        command += [args.xapp_image, "-c", "/usr/local/etc/flexric/xapp.conf",
                    "-p", "/usr/local/lib/flexric/"]
        text = run(command, 45)
        label = direction + ("-control" if control else "-context")
        (output / f"{label}.log").write_text(text)
        expected = 12345678 if direction == "A_TO_B" else 720898
        if not re.search(rf"UE\[0\]: serving .* cell={expected}\b", text):
            raise RuntimeError("Unexpected serving cell")
        if "E42 SUBSCRIPTION DELETE RESPONSE rx" not in text:
            raise RuntimeError("Subscription cleanup missing")
        if control and "CONTROL ACK rx" not in text:
            raise RuntimeError("Control ACK missing")

    try:
        saved = identities()
        ue_ip = address()
        if len(ue_ip) != 1:
            raise RuntimeError("Expected one UE IP")
        context("A_TO_B")
        ping_path = output / "continuous-ping.log"
        with ping_path.open("w") as handle:
            monitor = subprocess.Popen(docker + [
                "exec", names[3], "ping", "-D", "-n", "-I", "oaitun_ue1",
                "-i", "0.1", "-w", "120", "192.168.100.1",
            ], stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            time.sleep(5)
            if monitor.poll() is not None:
                raise RuntimeError("Continuous ping stopped before control")
            for direction, target in (("A_TO_B", names[2]), ("B_TO_A", names[1])):
                if monitor.poll() is not None:
                    raise RuntimeError("Ping coverage ended before control")
                started = datetime.now(timezone.utc).isoformat()
                context(direction, True)
                deadline = time.monotonic() + 45
                while True:
                    if identities() != saved:
                        raise RuntimeError("Process identity changed")
                    events = run(docker + ["logs", "--timestamps", "--since", started, target])
                    if re.search(r"handover for UE .* complete!", events) and "Handover Notify" in events:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Handover completion timeout")
                    time.sleep(1)
                selected = [line for line in events.splitlines()
                            if "handover" in line.lower() or "reconfiguration" in line.lower()]
                (output / f"{direction}-target-events.log").write_text(
                    "\n".join(selected) + "\n")
                opposite = "B_TO_A" if direction == "A_TO_B" else "A_TO_B"
                context(opposite)
                if address() != ue_ip:
                    raise RuntimeError("UE IP changed")
                summary["directions"].append({
                    "direction": direction, "requested_at": started,
                    "target_completion": True, "serving_context_verified": True,
                })
                print(f"PASS: {direction}, target completion and context", flush=True)
                time.sleep(5)
            if monitor.poll() is not None:
                raise RuntimeError("Ping coverage ended before post-control observation")
            monitor.wait(timeout=130)
        text = ping_path.read_text()
        replies = [(float(t), int(s)) for t, s in re.findall(
            r"^\[([\d.]+)\].*icmp_seq=(\d+).*time[=<]", text, re.MULTILINE)]
        if len(replies) < 20:
            raise RuntimeError("Insufficient ICMP replies")
        gaps = [b[0] - a[0] for a, b in zip(replies, replies[1:])]
        totals = re.search(r"(\d+) packets transmitted, (\d+) received", text)
        if totals is None:
            raise RuntimeError("Missing ping completion statistics")
        if identities() != saved or address() != ue_ip:
            raise RuntimeError("Final process or IP check failed")
        summary.update({
            "passed": True, "all_four_processes_unchanged": True,
            "ue_ip_unchanged": True, "ue_ip": ue_ip[0],
            "probe_interval_seconds": 0.1,
            "packets_sent": int(totals[1]), "packets_received": int(totals[2]),
            "maximum_observed_reply_gap_seconds": max(gaps),
            "measurement_scope": "ICMP reply gaps include probe spacing, RTT and scheduling; not exact radio interruption time.",
        })
        print(f"Measured maximum ICMP reply gap: {max(gaps):.3f}s", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        if monitor is not None and monitor.poll() is None:
            # Let the bounded container ping finish; killing docker exec alone
            # would not reliably terminate the in-container process.
            monitor.wait(timeout=130)
        for name in temporary:
            result = subprocess.run(docker + ["rm", "-f", name],
                                    capture_output=True, text=True, timeout=15)
            if result.returncode and "No such container" not in result.stderr:
                summary["cleanup_errors"].append(result.stderr)
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)

if __name__ == "__main__":
    main()
