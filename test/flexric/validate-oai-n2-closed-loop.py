#!/usr/bin/env python3
"""Validate two actual-traffic-triggered N2 transfers with feedback."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-n2-closed-loop-validation"))
    parser.add_argument("--inventory-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-cell-inventory-test")
    parser.add_argument("--control-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-n2-bidirectional-test")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Validation evidence: {output}", flush=True)
    root = Path(__file__).resolve().parents[2]
    docker = ["sudo", "docker"]
    server = "oai-loop-traffic-" + uuid.uuid4().hex[:10]
    controller = None
    owned_server = False
    summary = {"passed": False, "bursts": [], "cleanup_errors": [],
               "limitations": [
                   "MAC UL byte rate is not normalized cell utilization.",
                   "ICMP reply-gap interruption measurement is recorded separately.",
                   "One RFsim UE; transfer to an explicitly empty target cell."]}

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def run(command, timeout=25):
        return subprocess.run(command, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    try:
        result = run(docker + ["network", "inspect", "docker_open5gs_default"])
        result.check_returncode()
        for item in (json.loads(result.stdout)[0].get("Containers") or {}).values():
            require(item.get("IPv4Address", "").split("/")[0] != "172.22.0.151",
                    "Traffic server address occupied by " + item["Name"])
        result = run(docker + [
            "run", "-d", "--rm", "--pull", "never", "--name", server,
            "--network", "docker_open5gs_default", "--ip", "172.22.0.151",
            "--cap-add", "NET_ADMIN", "--entrypoint", "sh",
            "limx59/oai-nr-ue:arm64", "-c",
            "ip route add 192.168.100.0/24 via 172.22.0.8 && "
            "exec timeout --signal=INT --kill-after=5s 240s "
            "iperf3 -s -B 172.22.0.151"])
        result.check_returncode()
        owned_server = True
        result = run(docker + ["exec", "oai-pi-oai-e2-lab-nrue-1",
                              "ip", "-4", "-j", "addr", "show", "dev", "oaitun_ue1"])
        result.check_returncode()
        values = [a["local"] for interface in json.loads(result.stdout)
                  for a in interface.get("addr_info", []) if a.get("family") == "inet"]
        require(len(values) == 1, "Expected one UE IP")
        with (output / "controller.log").open("w") as stream:
            controller = subprocess.Popen([
                "python3", str(root / "test/flexric/run-oai-n2-closed-loop.py"),
                "--duration", "150", "--expected-actions", "2",
                "--output-dir", str(output / "controller"),
                "--inventory-image", args.inventory_image,
                "--control-image", args.control_image,
            ], stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            ready_deadline = time.monotonic() + 60
            while True:
                require(controller.poll() is None,
                        "Controller stopped before baseline readiness")
                paths = list((output / "controller").glob("run-*/decisions.jsonl"))
                ready = None
                if len(paths) == 1:
                    for line in paths[0].read_text().splitlines():
                        try:
                            decision = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        rates = decision.get("ul_bytes_per_second", [])
                        if (decision["reason"] == "below_threshold"
                                and not decision["action"] and len(rates) == 3
                                and all(rate <= 25000 for rate in rates)
                                and 0 <= time.time() - decision["at"] <= 3):
                            ready = decision
                if ready is not None:
                    summary["baseline_ready"] = ready
                    print("PASS: fresh low-rate baseline ready before traffic",
                          flush=True)
                    break
                require(time.monotonic() < ready_deadline,
                        "Valid low-rate baseline readiness timeout")
                time.sleep(0.5)
            for number in (1, 2):
                require(controller.poll() is None, "Controller stopped")
                start = time.time()
                print(f"Real UL burst {number}/2", flush=True)
                result = run(docker + [
                    "exec", "oai-pi-oai-e2-lab-nrue-1",
                    "timeout", "--kill-after=5s", "40s",
                    "iperf3", "-c", "172.22.0.151", "-B", values[0],
                    "--bind-dev", "oaitun_ue1", "-u", "-b", "1M",
                    "-l", "1200", "-t", "25", "-J",
                ], timeout=50)
                (output / f"burst-{number}.json").write_text(result.stdout)
                (output / f"burst-{number}.stderr.log").write_text(result.stderr)
                result.check_returncode()
                data = json.loads(result.stdout)
                require("error" not in data, data.get("error", ""))
                received = data["end"]["sum_received"]
                require(received["bytes"] > 0, "No received application traffic")
                summary["bursts"].append({
                    "start": start, "end": time.time(), "received": received})
                if number == 1:
                    time.sleep(40)
            controller.wait(timeout=100)
        print((output / "controller.log").read_text(), flush=True)
        require(controller.returncode == 0, "Controller failed")
        paths = list((output / "controller").glob("run-*/summary.json"))
        require(len(paths) == 1, "Expected one controller summary")
        evidence = paths[0].parent
        result = json.loads(paths[0].read_text())
        require(result["passed"] and not result["cleanup_errors"],
                "Controller summary failed")
        require(result["all_four_processes_unchanged"] and result["ue_ip_unchanged"],
                "Identity/IP validation missing")
        actions = result["actions"]
        require([(a["source"], a["target"]) for a in actions] ==
                [(3584, 2816), (2816, 3584)], "Unexpected action sequence")
        decisions = [json.loads(line) for line in
                     (evidence / "decisions.jsonl").read_text().splitlines()]
        idle = [d for d in decisions if d["at"] < summary["bursts"][0]["start"]]
        require(any(d["reason"] == "below_threshold" for d in idle),
                "No valid low-rate baseline decision")
        require(not any(d["action"] for d in idle), "Idle phase triggered control")
        require(any(d["reason"] == "cooldown" for d in decisions),
                "Cooldown observation missing")
        reports = [json.loads(line[len("MAC_REPORT "):])
                   for line in (evidence / "mac.log").read_text().splitlines()
                   if line.startswith("MAC_REPORT ")]
        growth = []
        for action, burst in zip(actions, summary["bursts"]):
            requested = datetime.fromisoformat(action["requested_at"]).timestamp()
            require(burst["start"] <= requested <= burst["end"],
                    "Action occurred outside its traffic burst")
            require(all(rate >= 100000 for rate in
                        action["decision"]["ul_bytes_per_second"]),
                    "Action threshold not confirmed")
            samples = [r for r in reports if r["node"] == action["target"]
                       and r["ues"] == 1
                       and requested + 2 <= r["report_us"] / 1e6 <= requested + 15]
            require(len(samples) >= 2, "Target MAC feedback missing")
            a, b = samples[0]["stats"][0], samples[-1]["stats"][0]
            require(a["rnti"] == b["rnti"] and b["ul_bytes"] > a["ul_bytes"],
                    "Target MAC counter growth not confirmed")
            growth.append({"node": action["target"],
                           "ul_mac_bytes_delta": b["ul_bytes"] - a["ul_bytes"]})
        summary.update(
            passed=True, actions=actions, target_mac_growth=growth,
            idle_no_action=True, cooldown_observed=True,
            all_four_processes_unchanged=True, ue_ip_unchanged=True,
            final_serving_node=result["final_serving_node"],
            decision_reasons=dict(Counter(d["reason"] for d in decisions)))
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        if controller is not None and controller.poll() is None:
            try:
                controller.wait(timeout=180)
            except subprocess.TimeoutExpired:
                controller.terminate()
                controller.wait(timeout=15)
                summary["cleanup_errors"].append("Controller required termination")
        if owned_server:
            try:
                result = run(docker + ["rm", "-f", server], timeout=15)
                if result.returncode and "No such container" not in result.stderr:
                    summary["cleanup_errors"].append(result.stderr)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if summary["cleanup_errors"]:
            summary["passed"] = False
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)
    if not summary["passed"]:
        raise RuntimeError("Validation or cleanup failed")
    print("PASS: actual-MAC closed loop, idle suppression, cooldown and feedback",
          flush=True)

if __name__ == "__main__":
    main()
