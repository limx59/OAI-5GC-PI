#!/usr/bin/env python3
"""Validate concurrent independent RFsim links and actual per-node MAC rates."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

UES = ["oai-pi-oai-e2-lab-nrue-1", "oai-pi-oai-e2-lab-nrue-2-1"]
NAMES = ["oai-pi-oai-e2-lab-ric-1", "oai-pi-oai-e2-lab-gnb-1",
         "oai-pi-oai-e2-lab-gnb-2-1", *UES]
NODES = (3584, 2816)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/oai-multi-cell-load"))
    parser.add_argument("--xapp-image",
                        default="limx59/oai-pi-flexric-xapp:arm64-oai-mac-100ms-test")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    root = Path(__file__).resolve().parents[2]
    config = root / "deploy/oai-flexric/config/oai/xapp-oai-context.conf"
    docker = ["sudo", "docker"]
    server = "oai-dual-traffic-" + uuid.uuid4().hex[:10]
    owned = set()
    collector = None
    started = datetime.now(timezone.utc).isoformat()
    summary = {"passed": False, "phases": [], "cleanup_errors": [],
               "scope": "Two independent RFsim links; MAC byte/PRB rates, not normalized utilization"}
    print(f"Evidence: {output}", flush=True)

    def run(command, timeout=20):
        return subprocess.run(command, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    def checked(command, timeout=20):
        result = run(command, timeout)
        require(result.returncode == 0, result.stderr[-1500:] or str(command))
        return result

    def identities():
        records = json.loads(checked(docker + ["inspect", *NAMES]).stdout)
        require(all(i["State"]["Running"] for i in records), "A process stopped")
        return {i["Name"].lstrip("/"): [
            i["Id"], i["Image"], i["State"]["Pid"], i["State"]["StartedAt"],
            i["RestartCount"], i["HostConfig"]["CpusetCpus"],
        ] for i in records}

    def addresses():
        values = {}
        for name in UES:
            result = checked(docker + ["exec", name, "ip", "-4", "-j",
                                      "addr", "show", "dev", "oaitun_ue1"])
            items = [a["local"] for interface in json.loads(result.stdout)
                     for a in interface.get("addr_info", [])
                     if a.get("family") == "inet"]
            require(len(items) == 1, "Missing UE address: " + name)
            values[name] = items[0]
        require(len(set(values.values())) == 2, "Duplicate UE IP")
        return values

    def reports(path):
        records = []
        for line in path.read_text().splitlines():
            if line.startswith("MAC_REPORT "):
                try:
                    records.append(json.loads(line[len("MAC_REPORT "):]))
                except json.JSONDecodeError:
                    continue
        return records

    def rates(records, node, start, end):
        items = sorted((r for r in records if r["node"] == node
                        and start <= r["report_us"] / 1e6 <= end),
                       key=lambda r: r["report_us"])
        require(len(items) >= 2, f"Missing MAC samples: {node}")
        require(all(r["ues"] == 1 and len(r["stats"]) == 1 for r in items),
                "Unexpected UE count")
        require(len({r["stats"][0]["rnti"] for r in items}) == 1, "RNTI changed")
        for a, b in zip(items, items[1:]):
            require(0 < b["report_us"] - a["report_us"] <= 2000000,
                    "MAC timestamp duplicate or gap exceeds two seconds")
            for key in ("ul_bytes", "dl_bytes", "ul_prb", "dl_prb"):
                require(b["stats"][0][key] >= a["stats"][0][key], "Counter reset")
        require(all(abs(r["received_us"] - r["report_us"]) <= 2000000
                    for r in items), "Delayed MAC report")
        seconds = (items[-1]["report_us"] - items[0]["report_us"]) / 1e6
        require(seconds >= 10, "MAC measurement window too short")
        return {"node": node, "seconds": seconds, "samples": len(items),
                **{key + "_per_second":
                   (items[-1]["stats"][0][key] - items[0]["stats"][0][key]) / seconds
                   for key in ("ul_bytes", "dl_bytes", "ul_prb", "dl_prb")}}

    try:
        before = identities()
        ips = addresses()
        summary["before"] = before
        summary["ue_addresses"] = ips
        network = json.loads(checked(docker + [
            "network", "inspect", "docker_open5gs_default"]).stdout)[0]
        require(not any(i.get("IPv4Address", "").split("/")[0] == "172.22.0.151"
                        for i in (network.get("Containers") or {}).values()),
                "Traffic server address occupied")
        script = (
            "ip route add 192.168.100.0/24 via 172.22.0.8 && "
            "exec timeout --signal=TERM --kill-after=5s 600s sh -c "
            "'iperf3 -s -B 172.22.0.151 -p 5201 & "
            "iperf3 -s -B 172.22.0.151 -p 5202 & wait'")
        owned.add(server)
        checked(docker + [
            "run", "-d", "--rm", "--pull", "never", "--name", server,
            "--network", "docker_open5gs_default", "--ip", "172.22.0.151",
            "--cap-add", "NET_ADMIN", "--entrypoint", "sh",
            "limx59/oai-nr-ue:arm64", "-c", script], 30)
        deadline = time.monotonic() + 10
        while True:
            result = checked(docker + ["exec", server, "ss", "-lnt"])
            if all(f"172.22.0.151:{port}" in result.stdout for port in (5201, 5202)):
                break
            require(time.monotonic() < deadline, "Server readiness timeout")
            time.sleep(0.5)

        for label, direction, offered in (
            ("ul-a-high", "ul", (1000000, 200000)),
            ("ul-b-high", "ul", (200000, 1000000)),
            ("dl-a-high", "dl", (1000000, 200000)),
            ("dl-b-high", "dl", (200000, 1000000)),
        ):
            directory = output / label
            directory.mkdir()
            name = "oai-dual-mac-" + uuid.uuid4().hex[:10]
            owned.add(name)
            print(f"Running {label}", flush=True)
            with (directory / "mac.log").open("w") as stream:
                collector = subprocess.Popen(docker + [
                    "run", "--rm", "--pull", "never", "--name", name,
                    "--network", "oai-pi-flexric-lab", "-e", "OAI_MAC_SECONDS=45",
                    "--mount", f"type=bind,src={config},dst=/usr/local/etc/flexric/xapp.conf,readonly",
                    args.xapp_image, "-c", "/usr/local/etc/flexric/xapp.conf",
                    "-p", "/usr/local/lib/flexric/",
                ], stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                deadline = time.monotonic() + 15
                while True:
                    require(collector.poll() is None, "Collector stopped early")
                    data = reports(directory / "mac.log")
                    now = time.time()
                    if all(sum(r["node"] == node and r["ues"] == 1
                               and 0 <= now - r["report_us"] / 1e6 <= 2
                               for r in data) >= 2 for node in NODES):
                        break
                    require(time.monotonic() < deadline, "MAC readiness timeout")
                    time.sleep(0.5)

                def traffic(index):
                    command = docker + [
                        "exec", UES[index], "timeout", "--kill-after=5s", "35s",
                        "iperf3", "-c", "172.22.0.151", "-p", str(5201 + index),
                        "-B", ips[UES[index]], "--bind-dev", "oaitun_ue1",
                        "-u", "-b", str(offered[index]), "-l", "1200",
                        "-t", "20", "-J"]
                    if direction == "dl":
                        command.append("-R")
                    start = time.time()
                    result = run(command, 45)
                    end = time.time()
                    (directory / f"ue-{index + 1}-iperf.json").write_text(result.stdout)
                    (directory / f"ue-{index + 1}-stderr.log").write_text(result.stderr)
                    require(result.returncode == 0, "iperf failed")
                    data = json.loads(result.stdout)
                    require("error" not in data, str(data.get("error")))
                    received = data["end"]["sum_received"]
                    require(received["bits_per_second"] >= offered[index] * 0.8
                            and received["lost_percent"] <= 5,
                            "Insufficient received rate or excessive loss")
                    return {"ue": UES[index], "offered_bps": offered[index],
                            "start": start, "end": end, "received": received}

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(traffic, i) for i in range(2)]
                    sample = 0
                    while not all(f.done() for f in futures):
                        require(identities() == before, "Process identity changed")
                        if sample % 5 == 0:
                            result = checked(docker + [
                                "stats", "--no-stream", "--format",
                                "{{.Name}}\t{{.CPUPerc}}", *NAMES], 25)
                            with (directory / "cpu.log").open("a") as cpu:
                                cpu.write(f"{time.time()}\n{result.stdout}")
                        sample += 1
                        time.sleep(1)
                    transfers = [f.result() for f in futures]
                require(collector.wait(timeout=40) == 0, "Collector failed")
            collector = None
            text = (directory / "mac.log").read_text()
            require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 2
                    and "Successfully stopped" in text, "Subscription cleanup incomplete")
            start = max(t["start"] for t in transfers) + 3
            end = min(t["end"] for t in transfers) - 2
            measured = [rates(reports(directory / "mac.log"), node, start, end)
                        for node in NODES]
            for record in measured:
                require(record[f"{direction}_bytes_per_second"] > 0
                        and record[f"{direction}_prb_per_second"] > 0,
                        "No actual MAC growth")
            require(identities() == before and addresses() == ips,
                    "Process or UE address changed")
            phase = {"label": label, "direction": direction,
                     "traffic": transfers, "mac": measured, "passed": True}
            summary["phases"].append(phase)
            print("PASS: " + label + ", traffic, actual MAC and cleanup", flush=True)

        for direction in ("ul", "dl"):
            a, b = [phase for phase in summary["phases"]
                    if phase["direction"] == direction]
            key = direction + "_bytes_per_second"
            require(a["mac"][0][key] > b["mac"][0][key] * 1.2
                    and b["mac"][1][key] > a["mac"][1][key] * 1.2,
                    "Per-node MAC rates did not follow exchanged offered load")
        summary["all_five_processes_unchanged"] = identities() == before
        summary["ue_ips_unchanged"] = addresses() == ips
        for name in NAMES[1:]:
            result = checked(docker + ["logs", "--timestamps", "--since", started, name])
            events = [line for line in (result.stdout + result.stderr).splitlines()
                      if any(m in line.lower() for m in
                             ("queue", "assertion", "no data for msg3", "exiting"))]
            (output / f"{name}-events.log").write_text("\n".join(events) + "\n")
            require(not events, "Queue or assertion events: " + name)
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        for name in sorted(owned):
            result = run(docker + ["rm", "-f", name])
            if result.returncode and "No such container" not in result.stderr:
                summary["cleanup_errors"].append(result.stderr.strip())
        if collector is not None and collector.poll() is None:
            collector.wait(timeout=20)
        if summary["cleanup_errors"]:
            summary["passed"] = False
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)
    require(summary["passed"], "Validation or cleanup failed")
    print("PASS: concurrent UL/DL, exchanged loads and actual per-node MAC feedback.",
          flush=True)

if __name__ == "__main__":
    main()
