#!/usr/bin/env python3
"""Bounded experimental controller driven by actual OAI MAC UL byte rates."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid
from oai_n2_closed_loop_policy import Policy, CELLS

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-n2-closed-loop"))
    parser.add_argument("--duration", type=int, default=180)
    parser.add_argument("--expected-actions", type=int, default=2)
    parser.add_argument("--inventory-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-cell-inventory-test")
    parser.add_argument("--control-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-n2-bidirectional-test")
    args = parser.parse_args()
    if not 30 <= args.duration <= 500 or args.expected_actions not in (0, 1, 2):
        parser.error("duration must be 30..500; expected-actions must be 0..2")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence: {output}", flush=True)
    root = Path(__file__).resolve().parents[2]
    config = root / "deploy/oai-flexric/config/oai/xapp-oai-context.conf"
    docker = ["sudo", "docker"]
    names = ["oai-pi-oai-e2-lab-ric-1", "oai-pi-oai-e2-lab-gnb-1",
             "oai-pi-oai-e2-lab-gnb-2-1", "oai-pi-oai-e2-lab-nrue-1"]
    policy = Policy()
    summary = {"passed": False, "actions": [], "cleanup_errors": [],
               "scope": "Actual MAC-rate-triggered transfer to an RC-confirmed empty cell; not capacity optimization"}
    collector = None
    temporary = set()
    sequence = 0

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def run(command, timeout=25):
        return subprocess.run(command, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    def identities():
        result = run(docker + ["inspect", *names])
        require(result.returncode == 0, result.stderr)
        states = {}
        for item in json.loads(result.stdout):
            require(item["State"]["Running"], item["Name"] + " stopped")
            states[item["Name"].lstrip("/")] = {
                "id": item["Id"], "image": item["Image"],
                "pid": item["State"]["Pid"],
                "started_at": item["State"]["StartedAt"],
                "restarts": item["RestartCount"],
                "cpuset": item["HostConfig"]["CpusetCpus"],
            }
        return states

    def address():
        result = run(docker + ["exec", names[3], "ip", "-4", "-j",
                              "addr", "show", "dev", "oaitun_ue1"])
        require(result.returncode == 0, result.stderr)
        values = [a["local"] for interface in json.loads(result.stdout)
                  for a in interface.get("addr_info", [])
                  if a.get("family") == "inet"]
        require(len(values) == 1, "Expected one UE IP")
        return values[0]

    def query(node, control=False):
        nonlocal sequence
        sequence += 1
        name = "oai-loop-query-" + uuid.uuid4().hex[:10]
        temporary.add(name)
        start = time.time()
        direction = "A_TO_B" if node == 3584 else "B_TO_A"
        command = docker + ["run", "--rm", "--name", name,
                           "--network", "oai-pi-flexric-lab",
                           "-e", "OAI_N2_DIRECTION=" + direction]
        if control:
            command += ["-e", "OAI_N2_CONTROL_TEST=1"]
        command += [
            "--mount",
            f"type=bind,src={config},dst=/usr/local/etc/flexric/xapp.conf,readonly",
            args.control_image if control else args.inventory_image,
            "-c", "/usr/local/etc/flexric/xapp.conf",
            "-p", "/usr/local/lib/flexric/"]
        try:
            result = run(command, timeout=40)
            text = result.stdout + result.stderr
        except subprocess.TimeoutExpired as error:
            def decode(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            text = decode(error.stdout) + decode(error.stderr)
            (output / f"query-{sequence}-{node}.log").write_text(text)
            raise
        (output / f"query-{sequence}-{node}.log").write_text(text)
        require(result.returncode == 0, f"Query/control exit={result.returncode}")
        require("E42 SUBSCRIPTION DELETE RESPONSE rx" in text,
                "RC subscription deletion not confirmed")
        if control:
            require("CONTROL ACK rx" in text, "Control ACK missing")
            return None
        require("CONTROL-REQUEST tx" not in text, "Inventory sent control")
        records = [json.loads(line[len("CELL_INVENTORY "):])
                   for line in text.splitlines()
                   if line.startswith("CELL_INVENTORY ")]
        require(len(records) == 1, "Expected one inventory")
        state = records[0]
        require(state["valid"] is True and state["node"] == node
                and state["cell"] == CELLS[node], "Inventory identity mismatch")
        require(start <= state["received_us"] / 1e6 <= time.time(),
                "Inventory not received during query")
        return state

    def reports():
        return [json.loads(line[len("MAC_REPORT "):])
                for line in (output / "mac.log").read_text().splitlines()
                if line.startswith("MAC_REPORT ") and line.endswith("}")]

    def verify_transfer(source, target, requested):
        target_name = names[1] if target == 3584 else names[2]
        deadline = time.monotonic() + 45
        while True:
            require(identities() == initial, "Process identity changed")
            result = run(docker + ["logs", "--timestamps", "--since",
                                  requested, target_name])
            text = result.stdout + result.stderr
            if re.search(r"handover for UE .* complete!", text) and "Handover Notify" in text:
                break
            require(time.monotonic() < deadline, "Target completion timeout")
            time.sleep(1)
        events = [line for line in text.splitlines()
                  if "handover" in line.lower() or "reconfiguration" in line.lower()]
        (output / f"action-{policy.actions}-target.log").write_text(
            "\n".join(events) + "\n")
        states = {source: query(source), target: query(target)}
        policy.feedback(source, target, states)
        require(address() == initial_ip, "UE IP changed")
        for node, expected in ((source, False), (target, True)):
            container = names[1] if node == 3584 else names[2]
            result = run(docker + ["exec", container, "python3", "-c",
                "from pathlib import Path; print(Path('/opt/oai-gnb/bin/nrRRC_stats.log').read_text())"])
            text = result.stdout + result.stderr
            (output / f"action-{policy.actions}-{node}-rrc.log").write_text(text)
            require(result.returncode == 0, "RRC stats unavailable")
            if expected:
                require("PDU session ID 1 status established" in text,
                        "Target PDU session not established")
            else:
                require("CU UE ID" not in text, "Source UE remains")
        result = run(docker + ["exec", names[3], "ping", "-I", "oaitun_ue1",
                              "-c", "5", "-W", "3", "192.168.100.1"], timeout=30)
        text = result.stdout + result.stderr
        (output / f"action-{policy.actions}-ping.log").write_text(text)
        require("5 packets transmitted, 5 received, 0% packet loss" in text,
                "Post-control connectivity failed")
        require(identities() == initial, "Process identity changed")
        return states

    try:
        initial = identities()
        initial_ip = address()
        (output / "before.json").write_text(json.dumps(
            {"processes": initial, "ue_ip": initial_ip}, indent=2) + "\n")
        state = {3584: query(3584), 2816: query(2816)}
        require(state[3584]["ues"] == 1 and state[2816]["ues"] == 0,
                "Initial topology must have one UE on A and zero on B")
        source = 3584
        name = "oai-loop-mac-" + uuid.uuid4().hex[:10]
        temporary.add(name)
        with (output / "mac.log").open("w") as stream:
            collector = subprocess.Popen(
                docker + ["run", "--rm", "--name", name,
                          "--network", "oai-pi-flexric-lab",
                          "-e", f"OAI_MAC_SECONDS={args.duration + 10}",
                          "--entrypoint", "stdbuf", "--mount",
                          f"type=bind,src={config},dst=/usr/local/etc/flexric/xapp.conf,readonly",
                          args.inventory_image, "-oL", "-eL",
                          "/usr/local/bin/xapp_oai_mac_counters",
                          "-c", "/usr/local/etc/flexric/xapp.conf",
                          "-p", "/usr/local/lib/flexric/"],
                stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            deadline = time.monotonic() + args.duration
            with (output / "decisions.jsonl").open("w") as decisions:
                while time.monotonic() < deadline:
                    require(collector.poll() is None, "MAC collector stopped")
                    require(identities() == initial, "Process identity changed")
                    now = time.time()
                    target = 2816 if source == 3584 else 3584
                    data = reports()
                    rates, _ = policy.rates(data, source, now)
                    if rates and all(r >= policy.high_bytes_per_second for r in rates):
                        if now - state[target]["received_us"] / 1e6 > 8:
                            state[target] = query(target)
                    decision = policy.evaluate(reports(), source, state, time.time())
                    decision["at"] = time.time()
                    decisions.write(json.dumps(decision) + "\n")
                    decisions.flush()
                    if decision["action"]:
                        requested = datetime.now(timezone.utc).isoformat()
                        policy.submitted(time.time())
                        print(f"Submitting actual-rate-triggered {source} -> {target}",
                              flush=True)
                        query(source, control=True)
                        state = verify_transfer(source, target, requested)
                        summary["actions"].append({
                            "source": source, "target": target,
                            "requested_at": requested, "decision": decision,
                            "feedback": state})
                        source = target
                        print(f"PASS: action {policy.actions}, state/session/IP/traffic/process feedback",
                              flush=True)
                    time.sleep(1)
            collector.wait(timeout=60)
        text = (output / "mac.log").read_text()
        require(collector.returncode == 0, "MAC collector failed")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 2,
                "MAC subscription cleanup not confirmed")
        require(len(summary["actions"]) == args.expected_actions,
                "Unexpected number of completed actions")
        require(identities() == initial and address() == initial_ip,
                "Final process/IP check failed")
        summary.update(passed=True, final_serving_node=source,
                       all_four_processes_unchanged=True, ue_ip_unchanged=True)
        print("PASS: bounded actual-MAC closed-loop run", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        for name in temporary:
            try:
                result = run(docker + ["rm", "-f", name], timeout=15)
                if result.returncode and "No such container" not in result.stderr:
                    summary["cleanup_errors"].append(result.stderr)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if collector is not None and collector.poll() is None:
            try:
                collector.wait(timeout=15)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if summary["cleanup_errors"]:
            summary["passed"] = False
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)

if __name__ == "__main__":
    main()
