#!/usr/bin/env python3
"""Validate namespace-isolated SCTP blackhole failover and explicit Agent rejoin."""

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
                        default=Path("/tmp/flexric-ric-blackhole-auto"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)
    root = Path(__file__).resolve().parents[2]
    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    for filename in (
        "compose.emulator.yaml", "compose.multi-agent.yaml",
        "compose.multi-ric.yaml", "compose.ric-failover.yaml",
        "compose.ric-blackhole.yaml", "compose.ric-rejoin.yaml",
    ):
        compose += ["-f", str(root / "deploy/oai-flexric" / filename)]
    a = "oai-pi-flexric-lab-ric-1"
    b = "oai-pi-flexric-lab-ric-2-1"
    agents = ["oai-pi-flexric-lab-emulator-1",
              "oai-pi-flexric-lab-emulator-2-1"]
    third = "oai-pi-flexric-lab-emulator-3-1"
    names = [a, b, *agents, third]
    temporary = []
    prefix = "blackhole-" + uuid.uuid4().hex[:10]
    table = "oai_pi_blackhole_" + uuid.uuid4().hex[:8]
    nft = None
    namespace = None
    before = None
    fault_attempted = False
    completed = False
    summary = {
        "passed": False,
        "scope": "Experimental socket settings, blackhole failover and explicit Agent rejoin",
        "limitations": [
            "Restoration recreates Agents; this is not proactive automatic failback.",
            "Fresh subscriptions are used; existing xApp subscriptions do not migrate.",
            "Active-subscription rejoin and production availability are not validated.",
        ],
    }

    def run(command, filename=None, timeout=30, input_text=None):
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout,
                input=input_text,
                stdin=subprocess.DEVNULL if input_text is None else None)
        except subprocess.TimeoutExpired as error:
            if filename:
                def decode(value):
                    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
                (output / filename).write_text(
                    decode(error.stdout) + decode(error.stderr), encoding="utf-8")
            raise
        if filename:
            (output / filename).write_text(
                result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0,
                f"Command failed ({result.returncode}): {' '.join(command)}")
        return result.stdout

    def inspect(phase):
        items = json.loads(run(docker + ["inspect", *names],
                               phase + "-inspect.json"))
        return {item["Name"].lstrip("/"): item for item in items}

    def identity(item):
        return (item["Id"], item["Image"], item["State"]["Pid"],
                item["State"]["StartedAt"], item["RestartCount"])

    def unchanged(items, selected):
        for name in selected:
            require(items[name]["State"]["Running"], f"{name} stopped")
            require(identity(items[name]) == identity(before[name]),
                    f"{name} process changed")

    def xapp(service, expected, phase, nodes=False):
        name = prefix + "-" + phase
        temporary.append(name)
        run(compose + [
            "--profile", "tools", "run", "-T", "--rm", "--no-deps",
            "--pull", "never", "--name", name, service,
        ], phase + ".log", timeout=45)
        text = (output / (phase + ".log")).read_text(encoding="utf-8")
        require(not any(marker in text for marker in (
            "Traceback", "Assertion", "callback error:", "DirectorMethodException",
        )), f"{phase}: xApp error")
        if nodes:
            found = set()
            for line in text.splitlines():
                match = re.fullmatch(r"\d+\s+(\d+)\s+\d+\s+\d+\s+\S+", line.strip())
                if match:
                    found.add(int(match[1]))
        else:
            found = {int(v) for v in re.findall(r"^KPM node=(\d+)", text, re.MULTILINE)}
            require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(expected),
                    f"{phase}: subscription cleanup incomplete")
        require(found == expected, f"{phase}: unexpected nodes {found}")
        summary[phase + "_nodes"] = sorted(found)
        print(f"PASS: {phase}, nodes={sorted(found)}", flush=True)

    def topology(phase):
        xapp("xapp-nodes", {1, 2}, phase + "-nodes-a", True)
        xapp("xapp-nodes-ric2", {3}, phase + "-nodes-b", True)
        xapp("xapp-kpm", {1, 2}, phase + "-kpm-a")
        xapp("xapp-kpm-ric2", {3}, phase + "-kpm-b")

    def namespace_check():
        item = inspect("namespace-check")[a]
        require(item["HostConfig"]["NetworkMode"] != "host", "Host networking rejected")
        unchanged({a: item}, [a])
        values = run(["sudo", "readlink", "/proc/1/ns/net",
                      f"/proc/{item['State']['Pid']}/ns/net"]).splitlines()
        require(len(values) == 2 and values[0] != values[1],
                "Namespace isolation failed")
        if namespace is not None:
            require(values[1] == namespace, "RIC namespace changed")
        return values

    def remove_fault():
        namespace_check()
        tables = run(nft + ["list", "tables"])
        if f"table ip {table}" in tables.splitlines():
            run(nft + ["list", "table", "ip", table], "final-counters.log")
            run(nft + ["delete", "table", "ip", table], "remove-fault.log")
        require(f"table ip {table}" not in run(nft + ["list", "tables"]).splitlines(),
                "Blackhole table remains")
        summary["blackhole_removed"] = True

    try:
        before = inspect("before")
        require(all(item["State"]["Running"] for item in before.values()),
                "Baseline containers must be running")
        for name in (a, b):
            require(before[name]["Config"]["Image"] ==
                    "limx59/flexric-ric:arm64-ric-rejoin", "Unexpected RIC image")
        for name in agents:
            require(before[name]["Config"]["Image"] ==
                    "limx59/flexric-emulator:arm64-ric-blackhole", "Unexpected Agent image")
            env = before[name]["Config"]["Env"]
            require("RIC_BLACKHOLE_TEST=1" in env and "RIC_BACKUP_IP=172.29.0.11" in env,
                    "Experimental Agent settings missing")
        require(before[a]["NetworkSettings"]["Networks"]["oai-pi-flexric-lab"]
                ["IPAddress"] == "172.29.0.10", "Unexpected RIC A address")
        for name, address in zip(agents, ("172.29.0.20", "172.29.0.21")):
            require(before[name]["NetworkSettings"]["Networks"]["oai-pi-flexric-lab"]
                    ["IPAddress"] == address, "Unexpected Agent address")
        topology("baseline")
        unchanged(inspect("baseline-complete"), names)
        values = namespace_check()
        namespace = values[1]
        nft = ["sudo", "nsenter", "-t", str(before[a]["State"]["Pid"]),
               "-n", "--", "/usr/sbin/nft"]
        require("oai_pi_blackhole" not in run(nft + ["list", "tables"]),
                "An existing blackhole test table is present")
        rules = f"""table ip {table} {{
 chain input {{
  type filter hook input priority 0; policy accept;
  ip saddr {{ 172.29.0.20, 172.29.0.21 }} ip protocol 132 counter drop
 }}
 chain output {{
  type filter hook output priority 0; policy accept;
  ip daddr {{ 172.29.0.20, 172.29.0.21 }} ip protocol 132 counter drop
 }}
}}
"""
        run(nft + ["-c", "-f", "-"], "validate-rules.log", input_text=rules)
        namespace_check()
        since = datetime.now(timezone.utc).isoformat()
        summary["fault_requested_at"] = since
        (output / "fault.json").write_text(json.dumps({
            "fault_requested_at": since, "host_namespace": values[0],
            "ric_namespace": namespace, "containers": list(before.values()),
            "rollback_command": nft + ["delete", "table", "ip", table],
        }, indent=2) + "\n", encoding="utf-8")
        fault_attempted = True
        run(nft + ["-f", "-"], "inject.log", input_text=rules)
        deadline = time.monotonic() + 120
        while True:
            unchanged(inspect("switch"), names)
            ready = True
            for name in agents:
                run(docker + ["logs", "--timestamps", "--since", since, name],
                    name + "-switch.log")
                text = (output / (name + "-switch.log")).read_text(encoding="utf-8")
                require("Assertion" not in text and "subscription cleanup failed" not in text,
                        f"{name}: failover error")
                ready &= ("switching 172.29.0.10 -> 172.29.0.11" in text
                          and "E2 SETUP RESPONSE rx" in text)
            if ready:
                break
            require(time.monotonic() < deadline, "Blackhole failover timeout")
            time.sleep(1)
        counters = run(nft + ["list", "table", "ip", table], "switch-counters.log")
        counts = [int(v) for v in re.findall(r"counter packets (\d+)", counters)]
        require(len(counts) == 2 and all(counts), "Bidirectional packet drops not confirmed")
        xapp("xapp-kpm-ric2", {1, 2, 3}, "backup-kpm")
        unchanged(inspect("after-backup-kpm"), names)
        summary["all_processes_unchanged_during_failover"] = True
        completed = True
        print("PASS: blackhole failover and backup KPM", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        errors = []
        for name in temporary:
            try:
                if run(docker + ["ps", "-aq", "--filter", "name=^/" + name + "$"]).strip():
                    run(docker + ["logs", "--timestamps", name], name + "-final.log")
                    run(docker + ["rm", "-f", name], name + "-remove.log")
            except Exception as error:
                errors.append(str(error))
        if fault_attempted:
            try:
                remove_fault()
                run(compose + [
                    "up", "-d", "--no-build", "--pull", "never", "--no-deps",
                    "--force-recreate", "emulator", "emulator-2",
                ], "recreate-agents.log", timeout=45)
                topology("restored")
                unchanged(inspect("final"), [a, b, third])
                summary["baseline_restored"] = True
                summary["ric_processes_unchanged_through_rejoin"] = True
                print("PASS: baseline restored; RIC processes unchanged", flush=True)
            except Exception as error:
                errors.append(str(error))
        summary["cleanup_errors"] = errors
        summary["passed"] = completed and not errors
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {output}", flush=True)
        if errors:
            raise RuntimeError(f"Cleanup/restoration errors: {errors}")


if __name__ == "__main__":
    main()
