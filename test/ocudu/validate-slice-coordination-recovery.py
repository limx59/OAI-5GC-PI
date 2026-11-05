#!/usr/bin/env python3
"""Validate dual-node controls from explicit laboratory demand fixtures."""
import json
import re
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ["sudo", "docker"]
CLIENT_ID = "sha256:6b9a231faec61a643b68582ae69701ce3e8da2e14ea62b829cc6325c27efb40e"
CLIENT = (
    "limx59/oai-pi-ocudu-slice-control-client:"
    "arm64-rrm-policy-ratio-ws-client-test@" + CLIENT_ID
)
GNBS = {"420": "gnb", "421": "gnb-2"}
UES = {"420": "nrue", "421": "nrue-2"}
GNB_ID = "sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b"
UE_ID = "sha256:bbdceed41714844717eaf9a06e09284f5404e27daff870d1f1ec08c782182047"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def invoke(args, timeout=30):
    return subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )


def output(args, timeout=30):
    result = invoke(args, timeout)
    require(result.returncode == 0,
            "Docker operation failed: " + " ".join(args[:2]))
    return result.stdout.strip()


def identity(cid):
    item = json.loads(output(["inspect", cid]))[0]
    return {
        "id": item["Id"], "image": item["Image"],
        "pid": item["State"]["Pid"],
        "started": item["State"]["StartedAt"],
        "restarts": item["RestartCount"],
        "running": item["State"]["Running"],
        "oom_killed": item["State"]["OOMKilled"],
    }


def healthy(value):
    return value["running"] and not value["oom_killed"]


def logs(cid):
    result = invoke(["logs", cid])
    require(result.returncode == 0, "Log collection failed")
    return {"stdout": result.stdout, "stderr": result.stderr}


def main():
    base = ROOT / "test/ocudu/.local/evidence"
    base.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix="ocudu-slice-coordination-recovery-", dir=base
    ))
    dest.chmod(0o700)
    print("Evidence:", dest, flush=True)
    project = "ocudu-slice-coord-recovery-" + uuid.uuid4().hex[:12]
    summary = {
        "passed": False,
        "scope": "Online client transport failure and same-plan reconciliation",
        "demand_source": "explicit synthetic fixtures",
        "control_requests_attempted": 0,
        "control_replies_validated": 0,
        "phases": [],
        "cleanup_errors": [],
        "raw_grant_effect_validated": False,
        "live_demand_reporting_validated": False,
        "failure_recovery_validated": False,
        "e2_control_validated": False,
    }
    compose = None
    touched = False
    baseline = {}
    containers = {}

    def save(name, value):
        path = dest / name
        path.write_text(
            value if isinstance(value, str)
            else json.dumps(value, indent=2) + "\n"
        )
        path.chmod(0o600)

    def ping(node, label):
        result = invoke([
            "exec", containers[UES[node]],
            "ping", "-I", "oaitun_ue1",
            "-c", "5", "-W", "3", "192.168.100.1",
        ], timeout=40)
        save(f"ping.{label}.{node}.log", result.stdout + result.stderr)
        strict_passed = (
            result.returncode == 0
            and "5 received" in result.stdout
            and "0% packet loss" in result.stdout
        )
        if not strict_passed:
            diagnostic = {
                "node": node,
                "phase": label,
                "strict_ping_passed": False,
                "test_processes": {},
                "baseline_processes": {},
            }
            for name, cid in containers.items():
                try:
                    diagnostic["test_processes"][name] = identity(cid)
                except Exception as error:
                    diagnostic["test_processes"][name] = {"error": str(error)}
            for cid in baseline:
                try:
                    diagnostic["baseline_processes"][cid] = identity(cid)
                except Exception as error:
                    diagnostic["baseline_processes"][cid] = {"error": str(error)}
            save(f"failure.{label}.{node}.json", diagnostic)
            try:
                stats = invoke([
                    "stats", "--no-stream", "--format", "{{json .}}",
                    *containers.values(),
                ], timeout=20)
                save(f"resources.{label}.{node}.jsonl",
                     stats.stdout + stats.stderr)
            except Exception as error:
                save(f"resources.{label}.{node}.error.log", str(error))
            try:
                followup = invoke([
                    "exec", containers[UES[node]],
                    "ping", "-I", "oaitun_ue1",
                    "-c", "5", "-W", "10", "-w", "30",
                    "192.168.100.1",
                ], timeout=40)
                save(f"ping.{label}.{node}.diagnostic.log",
                     followup.stdout + followup.stderr)
            except Exception as error:
                save(f"ping.{label}.{node}.diagnostic-error.log", str(error))
        require(result.returncode == 0
                and "5 received" in result.stdout
                and "0% packet loss" in result.stdout,
                "UE connectivity failed: " + node)

    try:
        with tempfile.TemporaryDirectory(prefix="private-", dir=dest) as tmp:
            try:
                private = Path(tmp)
                private.chmod(0o700)
                for relative in (
                    "prepare-slice-coordination.py",
                    "slice_coordination_policy.py",
                ):
                    path = ROOT / "test/ocudu" / relative
                    require(path.resolve().is_relative_to(ROOT)
                            and path.is_file(), "Missing helper: " + relative)

                memory = {
                    line.split(":")[0]: int(line.split()[1])
                    for line in Path("/proc/meminfo").read_text().splitlines()
                    if line.startswith("MemAvailable:")
                }
                require(memory["MemAvailable"] >= 3 * 1024 * 1024,
                        "Less than 3 GiB memory available")

                ids = output(["ps", "-q"]).split()
                baseline = {cid: identity(cid) for cid in ids}
                summary["baseline_before"] = baseline
                network = json.loads(output([
                    "network", "inspect", "docker_open5gs_default"
                ]))[0]
                occupied = {
                    entry.get("IPv4Address", "").split("/")[0]
                    for entry in network.get("Containers", {}).values()
                }
                require(not occupied.intersection({
                    "172.22.0.160", "172.22.0.161",
                    "172.22.0.164", "172.22.0.165",
                }), "Required dual-node address occupied")

                prepare = runpy.run_path(str(
                    ROOT / "test/ocudu/prepare-slice-coordination.py"
                ))["prepare"]
                config = private / "config"
                summary["configuration"] = prepare(ROOT, config)
                env = private / "compose.env"
                env.write_text(f"OCUDU_DUAL_CONFIG={config}\n")
                env.chmod(0o600)
                compose = [
                    "compose", "--project-name", project,
                    "--env-file", str(env), "-f",
                    str(ROOT / "deploy/ocudu/compose.slice-coordination.yaml"),
                    "-f", str(ROOT / "deploy/ocudu/compose.slice-coordination-cpu.yaml"),
                    "--profile", "ue",
                ]
                resolved = json.loads(output(
                    compose + ["config", "--format", "json"]
                ))
                expected = {
                    "gnb": GNB_ID, "gnb-2": GNB_ID,
                    "nrue": UE_ID, "nrue-2": UE_ID,
                }
                require(set(resolved["services"]) == set(expected),
                        "Unexpected service set")
                summary["resolved_cpu_sets"] = {
                    name: item.get("cpuset")
                    for name, item in resolved["services"].items()
                }
                require(all(
                    summary["resolved_cpu_sets"][name] == "2-3"
                    for name in ("nrue", "nrue-2")
                ), "UE CPU comparison overlay not applied")
                for service, digest in expected.items():
                    item = resolved["services"][service]
                    require(item["image"].endswith("@" + digest)
                            and item.get("pull_policy") == "never"
                            and not item.get("ports")
                            and not item.get("container_name"),
                            "Unexpected service configuration: " + service)
                    image = json.loads(output([
                        "image", "inspect", item["image"]
                    ]))[0]
                    require(image["Id"] == digest
                            and image["Architecture"] == "arm64"
                            and image["Os"] == "linux",
                            "Unexpected image: " + service)
                client_image = json.loads(output(
                    ["image", "inspect", CLIENT]
                ))[0]
                require(client_image["Id"] == CLIENT_ID,
                        "Unexpected control-client image")

                print("Starting independent dual-node project", flush=True)
                touched = True
                output(compose + [
                    "up", "-d", "--no-build", "--pull", "never",
                    "gnb", "gnb-2",
                ], timeout=90)
                output(compose + [
                    "up", "-d", "--no-build", "--pull", "never",
                    "nrue", "nrue-2",
                ], timeout=90)
                for service in expected:
                    cid = output(compose + ["ps", "--all", "-q", service])
                    require(len(cid.splitlines()) == 1 and cid,
                            "Missing or ambiguous test service")
                    containers[service] = cid
                summary["test_before"] = {
                    name: identity(cid) for name, cid in containers.items()
                }
                require(all(healthy(v) for v in summary["test_before"].values()),
                        "Test process not healthy")

                addresses = {}
                for node, service in UES.items():
                    deadline = time.monotonic() + 150
                    while time.monotonic() < deadline:
                        require(healthy(identity(containers[service])),
                                "UE process exited: " + node)
                        result = invoke([
                            "exec", containers[service], "ip", "-j", "-4",
                            "addr", "show", "dev", "oaitun_ue1",
                        ])
                        if result.returncode == 0:
                            candidates = [
                                a["local"] for item in json.loads(result.stdout)
                                for a in item.get("addr_info", [])
                                if a.get("family") == "inet"
                            ]
                            if len(candidates) == 1:
                                addresses[node] = candidates[0]
                                break
                        time.sleep(2)
                    require(node in addresses, "UE readiness timed out: " + node)
                    ping(node, "baseline")
                require(len(set(addresses.values())) == 2,
                        "UE tunnel addresses must differ")
                summary["ue_addresses"] = addresses

                Coordinator = runpy.run_path(str(
                    ROOT / "test/ocudu/slice_coordination_policy.py"
                ))["SliceCoordinator"]
                coordinator = Coordinator()
                revision = 0
                Executor = runpy.run_path(str(
                    ROOT / "test/ocudu/slice_coordination_executor.py"
                ))["CoordinatedExecutor"]
                histories = []
                for label, demands, ratio in (
                    ("limited-recovery", (80, 10), 20),
                    ("restored", (10, 10), 100),
                ):
                    print("Recovery phase:", label, flush=True)
                    for pair in range(2):
                        revision += 1
                        now = time.monotonic()
                        reports = {
                            node: {
                                "revision": revision,
                                "receipt_time_s": now,
                                "demand_prb_percent": demand,
                            }
                            for node, demand in zip(GNBS, demands)
                        }
                        decision = coordinator.evaluate(now, reports)
                        save(f"decision.{label}.{pair}.json", {
                            "input": reports, "result": decision,
                            "demand_source": "synthetic fixture",
                        })
                        require(decision["status"] == (
                            "pending_confirmation" if pair == 0 else "plan_ready"
                        ), "Unexpected recovery decision")
                    plan = decision["plan"]
                    executor = Executor(coordinator)
                    attempt_number = 0

                    def apply(node, cap, generation):
                        service = GNBS[node]
                        injected = (
                            label == "limited-recovery"
                            and attempt_number == 1 and node == "421"
                        )
                        tag = f"{label}.attempt{attempt_number}.{node}"
                        before = logs(containers[service])
                        save("gnb." + tag + ".before.json", before)
                        name = project + "-client-" + node
                        try:
                            summary["control_requests_attempted"] += 1
                            result = invoke([
                                "run", "--name", name, "--rm", "--pull=never",
                                "--network",
                                "none" if injected else
                                "container:" + containers[service],
                                CLIENT,
                                "--min-ratio", str(cap["min_prb_policy_ratio"]),
                                "--max-ratio", str(cap["max_prb_policy_ratio"]),
                            ], timeout=30)
                            save("control." + tag + ".log",
                                 result.stdout + result.stderr)
                        finally:
                            if output(["ps", "-a", "-q", "--filter",
                                       "name=^/" + name + "$"]):
                                output(["rm", "-f", name])
                        records = [
                            json.loads(line)
                            for line in result.stdout.splitlines()
                            if line.startswith("{")
                        ]
                        requests = [r for r in records
                                    if r.get("event") == "request"]
                        replies = [r for r in records
                                   if r.get("event") == "response"]
                        require(len(requests) == 1, "Expected one client request")
                        if injected:
                            errors = [r.get("error", "") for r in records
                                      if r.get("passed") is False]
                            require(result.returncode != 0 and not replies
                                    and any("connection refused" in e.lower()
                                            for e in errors),
                                    "Expected isolated-client connection refusal")
                        else:
                            require(result.returncode == 0 and len(replies) == 1
                                    and any(r.get("passed") is True for r in records),
                                    "Unexpected control failure")
                            summary["control_replies_validated"] += 1
                            ping(node, f"{label}-attempt{attempt_number}")

                        after = logs(containers[service])
                        save("gnb." + tag + ".after.json", after)
                        require(all(after[k].startswith(before[k]) for k in before),
                                "Scheduler history changed")
                        delta = "\n".join(
                            after[k][len(before[k]):] for k in before
                        )
                        events = delta.count("- Slice Reconfig: cell=0")
                        repeated = (
                            label == "limited-recovery"
                            and attempt_number == 2 and node == "420"
                        )
                        require(
                            events == 0 if injected else
                            events in (0, 1) if repeated else events == 1,
                            "Unexpected scheduler event count",
                        )
                        dl_check = None
                        if not injected:
                            header = re.compile(
                                r"^.*Slot decisions pci=1 .*?\((\d+) PDSCHs?, "
                                r"(\d+) PUSCHs?.*$", re.M,
                            )
                            grant = re.compile(
                                r"UE (PDSCH|PUSCH): ue=(\d+) "
                                r"c-rnti=(0x[0-9a-fA-F]+)"
                                r".*?\brb=\[(\d+)\.\.(\d+)\)"
                                r".*?\bnrtx=(\d+)\b"
                            )
                            # Use complete logged slots after the update,
                            # or the full retry interval for an unchanged cap.
                            segment = (
                                delta.split("- Slice Reconfig: cell=0", 1)[1]
                                if events else delta
                            )
                            headers = list(header.finditer(segment))
                            totals = []
                            parsed = 0
                            for i, match in enumerate(headers):
                                end = (headers[i + 1].start()
                                       if i + 1 < len(headers) else len(segment))
                                records = grant.findall(segment[match.end():end])
                                counts = {
                                    direction: sum(r[0] == direction for r in records)
                                    for direction in ("PDSCH", "PUSCH")
                                }
                                require(
                                    counts["PDSCH"] == int(match[1])
                                    and counts["PUSCH"] == int(match[2]),
                                    "Incomplete scheduler slot",
                                )
                                total = 0
                                for direction, ue, rnti, low, high, nrtx in records:
                                    parsed += 1
                                    low, high = int(low), int(high)
                                    require(ue == "0" and rnti.lower() == "0x4601"
                                            and nrtx == "0"
                                            and 0 <= low < high <= 51,
                                            "Unexpected grant identity or allocation")
                                    if direction == "PDSCH":
                                        total += high - low
                                if counts["PDSCH"]:
                                    totals.append(total)
                            require(parsed == len(re.findall(
                                r"UE (?:PDSCH|PUSCH):", segment
                            )), "Grant outside parsed slot blocks")
                            require(totals, "Missing actual DL grants")
                            if cap["max_prb_policy_ratio"] == 20:
                                require(max(totals) <= 10 and 10 in totals,
                                        "Actual DL cap not demonstrated")
                            else:
                                require(max(totals) > 10,
                                        "Actual DL restoration not demonstrated")
                            dl_check = {
                                "active_slots": len(totals),
                                "max_prbs_per_slot": max(totals),
                                "slots_above_10": sum(v > 10 for v in totals),
                            }
                        return {
                            "verified": not injected,
                            "fault_injected": injected,
                            "generation": generation,
                            "max_ratio": cap["max_prb_policy_ratio"],
                            "scheduler_events": events,
                            "same_plan_reapplication": repeated,
                            "dl_grant_check": dl_check,
                            "evidence_tag": tag,
                        }

                    if label == "limited-recovery":
                        attempt_number = 1
                        failed = executor.execute(plan, apply)
                        save("recovery.first-attempt.json", failed)
                        require(failed["status"] == "reconciliation_required",
                                "Partial failure was incorrectly committed")
                        results = failed["attempt"]["node_results"]
                        require(results["420"]["verified"] is True
                                and results["421"]["verified"] is False
                                and results["421"].get("fault_injected") is True,
                                "Expected real partial execution and injected failure")
                        require(coordinator.mode == "normal"
                                and coordinator.pending == plan,
                                "Coordinator lost pending plan")
                        try:
                            coordinator.evaluate(time.monotonic(), {})
                        except ValueError as error:
                            require(str(error) ==
                                    "Previous plan requires execution outcome",
                                    "New plan rejected for unexpected reason")
                        else:
                            raise RuntimeError("New plan allowed during recovery")
                        save("recovery.blocked-state.json", {
                            "new_plan_blocked": True,
                            "pending_plan": coordinator.pending,
                            "committed_mode": coordinator.mode,
                        })
                        attempt_number = 2
                    else:
                        attempt_number = 1

                    completed = executor.execute(plan, apply)
                    save("execution." + label + ".latest-result.json", completed)
                    save("execution." + label + ".attempt-history.json",
                         executor.evidence())
                    require(completed["status"] == "committed",
                            "Same-plan execution did not complete")
                    history = executor.evidence()
                    histories.append(history)
                    save("execution." + label + ".json", history)
                    summary["phases"].append({
                        "label": label, "max_ratio": ratio,
                        "generation": plan["generation"],
                        "attempts": len(history["attempts"]),
                        "coordinator_result": completed["coordinator_result"],
                    })
                require(summary["control_requests_attempted"] == 6
                        and summary["control_replies_validated"] == 5,
                        "Unexpected recovery request accounting")
                summary["execution_histories"] = histories
                summary["failure_recovery_validated"] = True
                summary["recovery_scope"] = (
                    "Isolated-client connection refusal, pending-plan blocking, "
                    "same-plan reapplication, replies, scheduler events and pings"
                )
                summary["atomic_cross_node_update"] = False

                summary["test_after"] = {
                    name: identity(cid) for name, cid in containers.items()
                }
                require(summary["test_before"] == summary["test_after"],
                        "Test process identities changed")
                summary["baseline_after"] = {
                    cid: identity(cid) for cid in baseline
                }
                require(baseline == summary["baseline_after"],
                        "Baseline process identities changed")
                summary["passed"] = True
            finally:
                for service, cid in containers.items():
                    try:
                        save(service + ".final-private.json", logs(cid))
                    except Exception as error:
                        summary.setdefault("diagnostic_errors", []).append(str(error))
                if touched:
                    result = invoke(compose + ["down"], timeout=90)
                    save("cleanup.log", result.stdout + result.stderr)
                    remaining = output([
                        "ps", "-a", "-q", "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]).split()
                    if remaining:
                        output(["rm", "-f", *remaining], timeout=60)
                    require(not output([
                        "ps", "-a", "-q", "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]), "Test containers remain after cleanup")
                    if result.returncode != 0:
                        summary["cleanup_errors"].append(
                            "Compose down failed; fallback removal completed"
                        )
    except Exception as error:
        summary["passed"] = False
        summary["error"] = str(error)
    finally:
        if summary["cleanup_errors"]:
            summary["passed"] = False
        save("summary.json", summary)
        print(json.dumps(summary, indent=2))
        print("Evidence:", dest)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
