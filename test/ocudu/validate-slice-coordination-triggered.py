#!/usr/bin/env python3
"""Calibrate actual DL queue observations with one TCP load; no controls."""
import argparse
from threading import Event
import json
import sys
from concurrent.futures import ThreadPoolExecutor
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load-node", choices=("420", "421"), default="420")
    args = parser.parse_args()
    load_node = args.load_node
    peer_node = "421" if load_node == "420" else "420"
    base = ROOT / "test/ocudu/.local/evidence"
    base.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix="ocudu-slice-coordination-triggered-", dir=base
    ))
    dest.chmod(0o700)
    print("Evidence:", dest, flush=True)
    project = "ocudu-slice-coord-triggered-" + uuid.uuid4().hex[:12]
    summary = {
        "passed": False,
        "scope": "Fixture-driven dual-node replies, scheduler events and pings",
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
                    "172.22.0.164", "172.22.0.165", "172.22.0.151",
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
                    "-f", str(ROOT / "deploy/ocudu/compose.slice-coordination-load.yaml"),
                    "--profile", "ue",
                ]
                resolved = json.loads(output(
                    compose + ["config", "--format", "json"]
                ))
                expected = {
                    "gnb": GNB_ID, "gnb-2": GNB_ID,
                    "nrue": UE_ID, "nrue-2": UE_ID,
                    "traffic": UE_ID,
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
                    "gnb", "gnb-2", "traffic",
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

                agent_path = ROOT / "test/ocudu/slice-node-agent.py"
                require(agent_path.resolve().is_relative_to(ROOT)
                        and agent_path.is_file(), "Missing node agent")
                agents = {}
                handles = []
                try:
                    for node, service in GNBS.items():
                        stdout_path = dest / f"agent.{node}.jsonl"
                        stderr_path = dest / f"agent.{node}.stderr.log"
                        stdout = stdout_path.open("x")
                        stderr = stderr_path.open("x")
                        stdout_path.chmod(0o600)
                        stderr_path.chmod(0o600)
                        handles.extend((stdout, stderr))
                        process = subprocess.Popen(
                            [sys.executable, "-B", str(agent_path),
                             "--node", node, "--container", containers[service],
                             "--reports", "5", "--sample-seconds", "4", "--step-input"],
                            stdout=stdout, stderr=stderr,
                            stdin=subprocess.PIPE, text=True,
                        )
                        agents[node] = (process, stdout_path)

                    deadline = time.monotonic() + 45
                    ready = set()
                    while time.monotonic() < deadline:
                        for node, (process, path) in agents.items():
                            require(process.poll() is None,
                                    "Node agent exited before sampling readiness")
                            for line in path.read_text().splitlines():
                                try:
                                    item = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                if item.get("event") == "agent_ready":
                                    require(item.get("node_id") == node,
                                            "Agent readiness node mismatch")
                                    ready.add(node)
                        if ready == set(GNBS):
                            break
                        time.sleep(0.1)
                    require(ready == set(GNBS), "Node agent readiness timeout")
                    print("Both agents sampling; TCP downlink to node", load_node,
                          flush=True)

                    sampling_ready = Event()

                    def downlink():
                        require(sampling_ready.wait(45),
                                "Sampling readiness timed out before load")
                        started = time.monotonic()
                        result = invoke([
                            "exec", containers[UES[load_node]],
                            "timeout", "--signal=TERM", "--kill-after=3s", "90s",
                            "iperf3", "-c", "172.22.0.151", "-p", "5201",
                            "-B", addresses[load_node],
                            "-R", "-b", "10M", "-t", "6",
                            "-J", "--get-server-output",
                        ], timeout=100)
                        ended = time.monotonic()
                        save(f"iperf-dl.node{load_node}.json", result.stdout)
                        save(f"iperf-dl.node{load_node}.stderr.log", result.stderr)
                        require(result.returncode == 0, "TCP DL process failed")
                        data = json.loads(result.stdout)
                        server = data.get("server_output_json")
                        require(isinstance(server, dict)
                                and not data.get("error")
                                and not server.get("error"),
                                "TCP DL client/server error or missing server JSON")
                        params = data.get("start", {}).get("test_start", {})
                        require(params.get("protocol") == "TCP"
                                and params.get("reverse") == 1
                                and params.get("duration") == 6
                                and params.get("num_streams") == 1,
                                "Unexpected TCP DL parameters")
                        connections = data.get("start", {}).get("connected", [])
                        require(len(connections) == 1
                                and connections[0].get("local_host") == addresses[load_node]
                                and connections[0].get("remote_host") == "172.22.0.151",
                                "TCP DL connection endpoint mismatch")
                        received = data.get("end", {}).get("sum_received", {})
                        sent = server.get("end", {}).get("sum_sent", {})
                        require(received.get("sender") is False
                                and received.get("bytes", 0) >= 65536
                                and received.get("bits_per_second", 0) > 0
                                and sent.get("bytes", 0) >= received["bytes"],
                                "Insufficient TCP DL receiver evidence")
                        return {
                            "node": load_node,
                            "transport": "TCP",
                            "direction": "downlink",
                            "host_start_s": started,
                            "host_end_s": ended,
                            "requested_rate_bits_per_second": 10000000,
                            "requested_duration_s": 6,
                            "sender": sent,
                            "receiver": received,
                        }

                    with ThreadPoolExecutor(max_workers=4) as pool:
                        collect = runpy.run_path(str(
                            ROOT / "test/ocudu/slice_queue_collection.py"
                        ))["collect"]
                        sources = {
                            node: summary["test_before"][service]["id"] + ":"
                                  + summary["test_before"][service]["started"]
                            for node, service in GNBS.items()
                        }
                        collection_future = pool.submit(
                            collect, agents, sources, 5, sampling_ready.set, save
                        )
                        load_future = pool.submit(downlink)
                        def probe_node(node):
                            require(sampling_ready.wait(45),
                                    "Sampling readiness timed out before probe")
                            result = invoke([
                                "exec", containers[UES[node]],
                                "ping", "-I", "oaitun_ue1",
                                "-c", "30", "-i", "1", "-W", "5",
                                "192.168.100.1",
                            ], timeout=60)
                            save("ping.load-probe." + node + ".log",
                                 result.stdout + result.stderr)
                            require(result.returncode == 0
                                    and "30 received" in result.stdout
                                    and "0% packet loss" in result.stdout,
                                    "Continuous node probe failed: " + node)

                        probe_futures = [
                            pool.submit(probe_node, node) for node in GNBS
                        ]
                        summary["live_queue_decisions"] = collection_future.result()
                        summary["downlink_load"] = load_future.result()
                        for future in probe_futures:
                            future.result()
                    for process, path in agents.values():
                        process.wait(timeout=60)
                        require(process.returncode == 0,
                                "Node observation process failed")

                    observations = {}
                    for node, (process, path) in agents.items():
                        records = [
                            json.loads(line)
                            for line in path.read_text().splitlines()
                            if line.strip()
                        ]
                        require(not any(
                            r.get("event") == "observation_error" for r in records
                        ), "Node observation error")
                        reports = [
                            r for r in records
                            if r.get("event") == "node_observation"
                        ]
                        require(len(reports) == 5
                                and [r["revision"] for r in reports] == [1, 2, 3, 4, 5],
                                "Unexpected report count or revisions")
                        service = GNBS[node]
                        original = summary["test_before"][service]
                        instance = original["id"] + ":" + original["started"]
                        for report in reports:
                            require(report["node_id"] == node
                                    and report["source_instance"] == instance
                                    and report["host_query_times_are_replay_fixtures"]
                                    is False
                                    and report["queue_unit"] == "bytes",
                                    "Unexpected live report provenance")
                            require(report["host_query_start_s"]
                                    < report["before_snapshot_received_s"]
                                    < report["host_query_end_s"],
                                    "Invalid host observation timing")
                        require(all(
                            left["host_query_end_s"] <= right["host_query_start_s"]
                            for left, right in zip(reports, reports[1:])
                        ), "Overlapping node query intervals")
                        require(sum(r["sample_count"] for r in reports) > 0,
                                "No actual DL samples from node " + node)
                        observations[node] = reports
                    summary["node_observations"] = observations
                    summary["live_queue_reporting_validated"] = True
                    summary["observations_used_for_control"] = False
                    summary["source_collection_time_validated"] = False
                finally:
                    for process, path in agents.values():
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                    for handle in handles:
                        handle.close()

                summary["scope"] = (
                    "Triggered two-node sampling and live queue-policy recommendations"
                )
                summary["demand_source"] = (
                    "Actual post-grant queue bytes; no demand-percent conversion"
                )
                require(summary["control_requests_attempted"] == 0
                        and summary["control_replies_validated"] == 0,
                        "Calibration must not send controls")
                summary["queue_calibration"] = {
                    node: {
                        "sample_count": sum(r["sample_count"] for r in reports),
                        "unknown_windows": sum(
                            r["observation_status"] == "unknown" for r in reports
                        ),
                        "queue_statistics_by_window": [
                            r["queue_statistics"] for r in reports
                        ],
                    }
                    for node, reports in summary["node_observations"].items()
                }
                summary["backlog_separation_validated"] = False
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
        compact = {
            key: summary.get(key)
            for key in (
                "passed", "scope", "error", "cleanup_errors",
                "control_requests_attempted", "queue_calibration",
            )
        }
        compact["live_queue_decisions"] = [
            {
                "revision": item["revision"],
                "status": item["result"]["status"],
                "candidate": item["result"]["candidate"],
                "recommended_max_ratio": item["result"]["recommended_max_ratio"],
            }
            for item in summary.get("live_queue_decisions", [])
        ]
        compact["load_node"] = load_node
        receiver = summary.get("downlink_load", {}).get("receiver", {})
        compact["dl_receiver_bytes"] = receiver.get("bytes")
        compact["dl_receiver_bits_per_second"] = receiver.get("bits_per_second")
        print(json.dumps(compact, indent=2))
        print("Evidence:", dest)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
