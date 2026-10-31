#!/usr/bin/env python3
"""Check concurrent dual-OCUDU links; preserve baseline services."""

from concurrent.futures import ThreadPoolExecutor
import json
import csv
import math
from datetime import datetime, timedelta
from statistics import median
from steering_dual_traffic_plateau import measure
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import uuid

from qos_startup_guard import wait_host_ready

DOCKER = ["sudo", "docker"]
BASE_RIC = "oai-pi-ocudu-zmq-lab-ric-1"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    require(result.returncode == 0, result.stderr.strip() or "Docker command failed")
    return result.stdout


def identity(name):
    value = json.loads(command(["inspect", name]))[0]
    return {
        "id": value["Id"], "image": value["Image"],
        "pid": value["State"]["Pid"],
        "started": value["State"]["StartedAt"],
        "restarts": value["RestartCount"],
        "running": value["State"]["Running"],
        "oom_killed": value["State"].get("OOMKilled", False),
    }


def tunnel(container):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        require(identity(container)["running"], "UE exited before readiness")
        try:
            value = subprocess.run(
                DOCKER + ["exec", container, "ip", "-j", "-4", "addr",
                          "show", "dev", "oaitun_ue1"],
                capture_output=True, text=True, timeout=12,
                stdin=subprocess.DEVNULL,
            )
            if value.returncode == 0:
                addresses = [
                    a["local"] for item in json.loads(value.stdout)
                    for a in item.get("addr_info", [])
                    if a.get("family") == "inet"
                ]
                if len(addresses) == 1:
                    return addresses[0]
        except subprocess.TimeoutExpired:
            pass
        time.sleep(1)
    raise RuntimeError("UE tunnel readiness timeout")


def ping(container, log_path):
    outputs = []
    passed = True
    with log_path.open("x") as stream:
        for probe in range(1, 6):
            result = subprocess.run(
                DOCKER + [
                    "exec", container, "ping", "-n", "-D",
                    "-I", "oaitun_ue1", "-c", "1", "-W", "3",
                    "192.168.100.1",
                ],
                capture_output=True, text=True, timeout=10,
                stdin=subprocess.DEVNULL,
            )
            output = result.stdout + result.stderr
            stream.write(f"=== Independent probe {probe}/5 ===\n")
            stream.write(output)
            stream.flush()
            outputs.append(output)
            passed = passed and (
                result.returncode == 0
                and "1 packets transmitted, 1 received" in output
                and " 0% packet loss" in output
            )
            if probe < 5:
                time.sleep(1)
    require(passed, "Concurrent UPF ping loss; inspect " + log_path.name)
    return "".join(outputs)


def main():
    image = json.loads(command([
        "image", "inspect",
        "limx59/oai-pi-ocudu-gnb:arm64-steering-prb-kpm-metadata-v2-test@sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b",
    ]))[0]
    require(
        image["Id"] ==
        "sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b"
        and image["Architecture"] == "arm64",
        "Unexpected PRB diagnostic image",
    )
    root = Path(__file__).resolve().parents[2]
    parent = root / "test/ocudu/.local/evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-embedded-online-published-v2-", dir=parent))
    dest.chmod(0o700)
    print(f"Evidence: {dest}", flush=True)
    summary = {
        "passed": False, "cleanup_errors": [],
        "scope": "Dual-node downlink load measurement and KPM association; no steering control",
        "steering_recommendation_validated": False,
        "control_executed": False,
    }
    baseline = None
    touched = False
    compose = None
    core_before = None
    with tempfile.TemporaryDirectory(
            prefix="ocudu-dual-private-", dir=dest) as private:
        try:
            for name in (
                "oai-pi-ocudu-zmq-lab-gnb-1",
                "oai-pi-ocudu-zmq-lab-nrue-1",
            ):
                require(not command([
                    "ps", "-q", "--filter", "name=^/" + name + "$",
                ]).strip(), "Original test RAN is running")
            core_names = (
                "ausf", "udm", "udr", "nrf", "scp", "amf", "smf", "upf",
            )
            core_before = {name: identity(name) for name in core_names}
            summary["core_before"] = core_before
            require(all(item["running"] for item in core_before.values()),
                    "Core service is not running")
            require(core_before["ausf"]["image"] ==
                    "sha256:7ba6049f69cde00ba19eb19319020ea7d3d078b040bd0ecf122398f8fa96f3c4",
                    "Expected patched AUSF image is not active")
            require(core_before["amf"]["image"] ==
                    "sha256:b628a243937160288cdf5639e4407d104fb95dac7eb4e9c9a37a5fbda4180624",
                    "Expected patched AMF image is not active")
            memory = {
                line.split(":")[0]: int(line.split()[1])
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith(("MemAvailable:", "SwapFree:"))
            }
            summary["memory_before_kib"] = memory
            require(memory["MemAvailable"] >= 3 * 1024 * 1024,
                    "Less than 3 GiB available; dual-node run deferred")
            for name in (
                "deploy/ocudu/config/gnb-zmq-e2.yml",
                "deploy/ocudu/.local/ue-zmq.conf",
                "deploy/oai-flexric/config/oai/ue-2.conf",
                "deploy/ocudu/config/ric.conf",
                "deploy/ocudu/config/xapp.conf",
                "test/ocudu/prepare-steering-dual-node-pci-control.py",
                "deploy/ocudu/compose.steering-dual-node.yaml",
            ):
                path = root / name
                require(path.resolve().is_relative_to(root.resolve())
                        and path.is_file(), "Unexpected review input: " + name)
            baseline = identity(BASE_RIC)
            require(baseline["running"], "Baseline RIC must remain running")
            summary["baseline_ric_before"] = baseline
            network = json.loads(command([
                "network", "inspect", "docker_open5gs_default",
            ]))[0]
            occupied = {
                item.get("IPv4Address", "").split("/")[0]
                for item in network.get("Containers", {}).values()
            }
            require(not occupied.intersection({
                "172.22.0.160", "172.22.0.161", "172.22.0.163",
                "172.22.0.164", "172.22.0.165", "172.22.0.151",
            }), "Required dual-node address occupied")
            prepare = runpy.run_path(str(
                root / "test/ocudu/prepare-steering-dual-node-pci-control.py"
            ))["prepare"]
            config = Path(private) / "config"
            summary["configuration"] = prepare(root, config)
            env_file = Path(private) / "compose.env"
            env_file.write_text(
                f"OCUDU_DUAL_CONFIG={config}\n"
                f"OCUDU_DUAL_EVIDENCE={dest}\n"
            )
            env_file.chmod(0o600)
            require(summary["configuration"]["buffer_pool_segments_per_gnb"]
                    == 65536, "Unexpected buffer pool size")
            compose = [
                "compose", "--project-name", "ocudu-dual-" + uuid.uuid4().hex[:12],
                "--env-file", str(env_file), "-f",
                str(root / "deploy/ocudu/compose.steering-dual-node.yaml"),
                "-f", str(root / "deploy/ocudu/compose.steering-dual-node-collector.yaml"),
                "-f", str(root / "deploy/ocudu/compose.steering-dual-node-load.yaml"),
                "-f", str(root / "deploy/ocudu/compose.steering-dual-node-timeout.yaml"),
                "-f", str(root / "deploy/ocudu/compose.steering-prb-source-trace.yaml"),
                "-f", str(root / "deploy/ocudu/compose.steering-prb-kpm-metadata-v2.yaml"),
                "-f", str(root / "deploy/ocudu/compose.steering-embedded-online-published.yaml"),
                "--profile", "ue",
            ]
            resolved = json.loads(command(compose + ["config", "--format", "json"]))
            summary["images"] = {
                image: json.loads(command(["image", "inspect", image]))[0]["Id"]
                for image in {
                    service["image"] for service in resolved["services"].values()
                }
            }
            require(
                summary["images"].get('limx59/oai-pi-ocudu-flexric-xapp:arm64-steering-embedded-online-test@sha256:502b970b4c20285e1ad8cd17ac6536cfc99d482d4cf834ae40b2427a9e5c7561') == 'sha256:502b970b4c20285e1ad8cd17ac6536cfc99d482d4cf834ae40b2427a9e5c7561',
                "Unexpected online xApp image")
            summary["host_readiness"] = wait_host_ready(dest / "host-readiness.json")
            touched = True
            command(compose + [
                "up", "-d", "--no-deps", "--no-build", "--pull", "never", "ric",
            ], timeout=60)
            time.sleep(2)
            command(compose + [
                "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                "gnb", "gnb-2",
            ], timeout=90)
            time.sleep(5)
            command(compose + [
                "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                "nrue", "nrue-2",
            ], timeout=90)
            containers = {
                service: command(compose + ["ps", "--all", "-q", service]).strip()
                for service in ("ric", "gnb", "gnb-2", "nrue", "nrue-2")
            }
            require(all(containers.values()), "Missing test container")
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {
                    name: pool.submit(tunnel, containers[name])
                    for name in ("nrue", "nrue-2")
                }
                addresses = {name: future.result() for name, future in futures.items()}
            require(len(set(addresses.values())) == 2, "UE tunnel addresses must differ")
            summary["ue_addresses"] = addresses
            before = {name: identity(cid) for name, cid in containers.items()}
            require(all(v["running"] and not v["oom_killed"] for v in before.values()),
                    "Test process unhealthy")
            summary["processes_before"] = before
            for round_number in (1, 2):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = {
                        name: pool.submit(
                            ping, containers[name],
                            dest / f"ping-{round_number}-{name}.log",
                        )
                        for name in ("nrue", "nrue-2")
                    }
                    for name, future in futures.items():
                        future.result()
                require({name: identity(cid) for name, cid in containers.items()}
                        == before, "Test process identity changed")
                require({name: tunnel(containers[name]) for name in addresses}
                        == addresses, "UE tunnel address changed")
                print(f"PASS: concurrent ping round {round_number}", flush=True)
                if round_number == 1:
                    time.sleep(20)
            command(compose + [
                "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                "traffic-server",
            ], timeout=60)
            server = command(compose + [
                "ps", "--all", "-q", "traffic-server",
            ]).strip()
            require(bool(server), "Traffic server missing")
            server_before = identity(server)
            require(server_before["running"], "Traffic server exited")
            time.sleep(2)
            for name in addresses:
                command([
                    "exec", containers[name], "ping", "-I", "oaitun_ue1",
                    "-c", "3", "-W", "2", "172.22.0.151",
                ], timeout=20)
            command(compose + [
                "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                "dual-node-collector",
            ], timeout=60)
            collector = command(compose + [
                "ps", "--all", "-q", "dual-node-collector",
            ]).strip()
            require(bool(collector), "Collector container missing")
            deadline = time.monotonic() + 25
            while True:
                require(identity(collector)["running"],
                        "Collector exited before report readiness")
                seen = {"420": set(), "421": set()}
                csv_path = dest / "kpm.csv"
                if csv_path.is_file():
                    with csv_path.open() as stream:
                        for row in csv.DictReader(stream):
                            node = row.get("node_id")
                            if node in seen:
                                seen[node].add(row.get("report_sequence"))
                if all(len(values) >= 3 for values in seen.values()):
                    break
                require(time.monotonic() < deadline,
                        "Both-node KPM readiness timeout")
                time.sleep(1)
            summary["traffic_phases"] = measure(
                command, containers, addresses, dest)
            require(identity(server) == server_before,
                    "Traffic server stopped or restarted during measurement")
            deadline = time.monotonic() + 240
            while True:
                value = json.loads(command(["inspect", collector]))[0]
                if not value["State"]["Running"]:
                    require(value["State"]["ExitCode"] == 0,
                            "Collector failed; inspect retained private logs")
                    require(not value["State"].get("OOMKilled"),
                            "Collector was OOM killed")
                    break
                require(time.monotonic() < deadline, "Collector completion timeout")
                time.sleep(1)

            probe = json.loads((dest / "probe.json").read_text())
            require(probe.get("passed"), "Collector callback or cleanup failed")
            summary["collector"] = probe

            with (dest / "kpm.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            require(bool(rows), "KPM CSV empty")
            expected_metrics = set(probe["metrics"])
            require(expected_metrics == {
                "RRU.PrbAvailDl", "RRU.PrbAvailUl",
                "RRU.PrbUsedDl", "RRU.PrbUsedUl",
                "RRU.PrbTotDl", "RRU.PrbTotUl",
                "DRB.RlcSduTransmittedVolumeDL",
                "DRB.RlcSduTransmittedVolumeUL",
                "DRB.UEThpDl", "DRB.UEThpUl",
                "OAI.PI.PrbSourceRevision",
                "OAI.PI.PrbReceiptMonoSec",
                "OAI.PI.PrbReceiptMonoUsec",
                "OAI.PI.PrbQueryMonoSec",
                "OAI.PI.PrbQueryMonoUsec",
            }, "Unexpected metadata metric set")
            groups = {}
            ue_ids = {"420": set(), "421": set()}
            for row in rows:
                node = row["node_id"]
                require(node in ue_ids, "Unexpected KPM node")
                require((row["mcc"], row["mnc"]) == ("1", "1"),
                        "Unexpected KPM PLMN")
                require(row["incomplete"] == "0", "Incomplete KPM row")
                require(row["granularity_ms"] == "1000",
                        "Unexpected KPM granularity")
                require(row["window_basis"] ==
                        "header_plus_row_granularity_nominal",
                        "Unexpected KPM time basis")
                ue_ids[node].add(row["gnb_cu_ue_f1ap"])
                key = (
                    node, row["report_sequence"], row["ue_report_index"],
                    row["row_index"],
                )
                groups.setdefault(key, []).append(row["measurement"])
                if row["measurement"] in ("RRU.PrbTotDl", "RRU.PrbTotUl"):
                    require(row["unit"] == "percent" and
                            row["statistic_basis"] == "integer_prb_utilization",
                            "Unexpected PRB load semantics")
                    require(row["value_type"] in ("integer", "real"),
                            "Missing numeric PRB utilization")
                    require(0 <= float(row["value"]) <= 100,
                            "PRB utilization outside 0..100")

            provenance = {}
            for row in rows:
                key = (
                    row["node_id"], row["report_sequence"],
                    row["ue_report_index"], row["row_index"],
                )
                record = provenance.setdefault(key, {})
                require(row["measurement"] not in record,
                        "Duplicate measurement in metadata group")
                record[row["measurement"]] = row

            batches = {"420": {}, "421": {}}
            previous = {}
            for key, record in provenance.items():
                node = key[0]
                revision_row = record["OAI.PI.PrbSourceRevision"]
                require(revision_row["value_type"] == "integer",
                        "Missing integer source revision")
                revision = int(revision_row["value"])
                require(0 < revision <= 2147483647,
                        "Invalid source revision")
                times = []
                for stem in ("OAI.PI.PrbReceiptMono", "OAI.PI.PrbQueryMono"):
                    parts = []
                    for suffix, unit, upper in (
                        ("Sec", "seconds", 2147483647),
                        ("Usec", "microseconds", 999999),
                    ):
                        row = record[stem + suffix]
                        require(row["value_type"] == "integer"
                                and row["unit"] == unit,
                                "Missing integer timestamp component")
                        value = int(row["value"])
                        require(0 <= value <= upper,
                                "Timestamp component outside range")
                        parts.append(value)
                    times.append(parts[0] * 1000000 + parts[1])
                receipt, query = times
                require(0 < receipt <= query,
                        "Source timestamp order invalid")
                load = float(record["RRU.PrbTotDl"]["value"])
                if node in previous:
                    old_revision, old_query = previous[node]
                    require(revision >= old_revision and query >= old_query,
                            "Source revision or query time moved backwards")
                previous[node] = (revision, query)
                if revision in batches[node]:
                    require(batches[node][revision] == (receipt, load),
                            "Same source revision changed receipt time or PRB value")
                else:
                    batches[node][revision] = (receipt, load)
            require(all(len(values) >= 20 for values in batches.values()),
                    "Insufficient independent source batches")
            summary["prb_kpm_metadata"] = {
                "delivery_validated": True,
                "same_revision_values_consistent": True,
                "independent_source_batches": {
                    node: len(values) for node, values in batches.items()
                },
                "clock_basis": "Provider steady-clock integer microseconds",
                "cross_process_clock_validated": False,
                "collection_window_alignment_validated": False,
                "online_advisory_validated": False,
            }

            counts = {"420": 0, "421": 0}
            for key, metrics in groups.items():
                require(len(metrics) == 15 and set(metrics) == expected_metrics,
                        "Incomplete or duplicate metric group")
                counts[key[0]] += 1
            require(all(value >= 20 for value in counts.values()),
                    "Insufficient KPM groups for one or both nodes")
            require(all(len(values) == 1 and "" not in values
                        for values in ue_ids.values()),
                    "Expected one stable UE identity per node")
            require({name: identity(cid) for name, cid in containers.items()}
                    == before, "RAN/RIC identity changed during collection")
            require({name: tunnel(containers[name]) for name in addresses}
                    == addresses, "UE tunnel changed during collection")
            summary["per_node_metric_groups"] = counts
            summary["per_node_ue_ids"] = {
                node: sorted(values) for node, values in ue_ids.items()
            }
            phase_review = {}
            for phase, record in summary["traffic_phases"].items():
                phase_review[phase] = {}
                for node, traffic in record["nodes"].items():
                    start = datetime.fromisoformat(
                        traffic["started_utc"]) + timedelta(seconds=2)
                    end = datetime.fromisoformat(
                        traffic["finished_utc"]) - timedelta(seconds=1)
                    values = []
                    windows = set()
                    for row in rows:
                        if (row["node_id"] != node or
                                row["measurement"] != "RRU.PrbTotDl"):
                            continue
                        left = datetime.fromisoformat(
                            row["nominal_window_start_utc"])
                        right = datetime.fromisoformat(
                            row["nominal_window_end_utc"])
                        if left >= start and right <= end:
                            require((left, right) not in windows,
                                    "Duplicate node/window PRB measurement")
                            windows.add((left, right))
                            values.append(float(row["value"]))
                    require(len(values) >= 5,
                            "Insufficient interior PRB windows: " + phase + "/" + node)
                    phase_review[phase][node] = {
                        "interior_reports": len(values),
                        "median_prb_percent": median(values),
                        "min_prb_percent": min(values),
                        "max_prb_percent": max(values),
                        "offered_bit_s": traffic["offered_bit_s"],
                        "received_bit_s": traffic["receiver"]["bits_per_second"],
                        "lost_percent": traffic["receiver"]["lost_percent"],
                        "traffic_quality_passed": traffic["traffic_quality_passed"],
                    }
            summary["phase_load_review"] = phase_review
            summary["all_traffic_quality_checks_passed"] = all(
                item["traffic_quality_passed"]
                for phase in phase_review.values() for item in phase.values()
            )
            summary["dual_node_load_measurement_validated"] = True
            summary["dual_node_collection_validated"] = True
            require(probe.get("online_advisory_enabled") is True,
                    "Online advisor was not enabled")
            online = probe["online_advisory"]
            require(online.get("control_executed") is False,
                    "Unexpected online control state")
            policy_config = json.loads((
                root / "test/ocudu/config/steering-dual-node-embedded-async.json"
            ).read_text())
            policy = policy_config["policy"]
            checks = policy_config["input_checks"]
            entries = [
                json.loads(line)
                for line in (dest / "advisory.jsonl").read_text().splitlines()
                if line.strip()
            ]
            require(bool(entries), "Online decision evidence empty")
            used = {"420": set(), "421": set()}
            recommendations = []
            cooldowns = 0
            previous_time = None
            last_recommendation = None
            for entry in entries:
                stamp = entry["decision_monotonic_seconds"]
                require(math.isfinite(stamp) and
                        (previous_time is None or stamp > previous_time),
                        "Online decision time did not increase")
                previous_time = stamp
                result = entry["result"]
                require(result.get("control_executed") is False,
                        "Unexpected decision control state")
                if result["status"] == "input_rejected":
                    continue
                observations = entry["observations"]
                require(set(observations) == set(used),
                        "Unexpected online node set")
                for node, item in observations.items():
                    revision = item["revision"]
                    require(revision == entry["revisions"][node]
                            and revision not in used[node],
                            "Online source batch reused or mismatched")
                    used[node].add(revision)
                    require(0 <= item["load"] <= 1 and
                            0 <= item["receipt_time_s"]
                            <= item["query_time_s"] <= stamp,
                            "Invalid online observation")
                    require(stamp - item["receipt_time_s"]
                            <= checks["max_receipt_age_seconds"],
                            "Online source age exceeded budget")
                require(abs(observations["420"]["query_time_s"]
                            - observations["421"]["query_time_s"])
                        <= checks["max_query_skew_seconds"],
                        "Online query skew exceeded budget")
                if result["status"] in ("recommendation", "cooldown"):
                    source_node, target_node = result["source"], result["target"]
                    high = observations[source_node]["load"]
                    low = observations[target_node]["load"]
                    require(source_node != target_node
                            and high >= policy["source_load_min"]
                            and low <= policy["target_load_max"]
                            and (high - low >= policy["load_difference_min"]
                                 or math.isclose(
                                     high - low, policy["load_difference_min"],
                                     rel_tol=0, abs_tol=1e-12))
                            and result["independent_pairs"]
                            >= policy["consecutive_independent_pairs"],
                            "Online recommendation criteria not met")
                if result["status"] == "recommendation":
                    require(last_recommendation is None or
                            stamp - last_recommendation
                            >= policy["cooldown_seconds"],
                            "Recommendation violated cooldown")
                    last_recommendation = stamp
                    recommendations.append(entry)
                elif result["status"] == "cooldown":
                    require(last_recommendation is not None and
                            stamp - last_recommendation
                            < policy["cooldown_seconds"],
                            "Unexpected cooldown result")
                    cooldowns += 1
            require(recommendations == online["recommendations"],
                    "Probe and online decision log disagree")
            require({
                (item["result"]["source"], item["result"]["target"])
                for item in recommendations
            } == {("420", "421"), ("421", "420")},
                    "Both online recommendation directions not observed")
            require(cooldowns > 0, "Online cooldown not observed")
            summary["online_advisory_acceptance"] = {
                "validated": True,
                "bidirectional": True,
                "admitted_source_batches_unique": True,
                "cooldown_observed": True,
                "recommendations": recommendations,
                "collection_window_alignment_validated": False,
                "control_executed": False,
            }
            summary["steering_recommendation_validated"] = True
            summary["passed"] = True
        except Exception as error:
            summary["error"] = str(error)
        finally:
            if touched:
                try:
                    ids = command([
                        "ps", "-a", "-q", "--filter",
                        "label=com.docker.compose.project=" + compose[2],
                    ]).split()
                    diagnostics = []
                    markers = (
                        "NG Setup", "E2 Setup", "Registration Accept",
                        "PDU Session Establishment Accept", "TUN Interface",
                        "Assertion", "terminate", "Error", "Failed",
                        "RRC reestablishment", "PUSCH DTX",
                    )
                    for cid in ids:
                        value = json.loads(command(["inspect", cid]))[0]
                        labels = value["Config"].get("Labels") or {}
                        require(labels.get("com.docker.compose.project")
                                == compose[2], "Unexpected diagnostic project")
                        logs = subprocess.run(
                            DOCKER + ["logs", cid],
                            capture_output=True, text=True, timeout=20,
                            stdin=subprocess.DEVNULL,
                        )
                        combined = logs.stdout + logs.stderr
                        # Private runtime logs may contain subscriber credentials.
                        import os
                        service = labels.get("com.docker.compose.service", "unknown")
                        private_log = dest / (service + ".runtime-private.log")
                        with open(
                            private_log, "x",
                            opener=lambda p, flags: os.open(p, flags, 0o600),
                        ) as stream:
                            stream.write(combined)
                        diagnostics.append({
                            "id": cid,
                            "service": labels.get("com.docker.compose.service"),
                            "state": value["State"],
                            "restarts": value["RestartCount"],
                            "event_counts": {
                                marker: combined.lower().count(marker.lower())
                                for marker in markers
                            },
                        })
                    (dest / "process-diagnostics.json").write_text(
                        json.dumps(diagnostics, indent=2) + "\n"
                    )
                except Exception as error:
                    summary["diagnostic_error"] = str(error)
            if touched:
                try:
                    value = subprocess.run(
                        DOCKER + compose + ["down"],
                        capture_output=True, text=True, timeout=90,
                        stdin=subprocess.DEVNULL,
                    )
                    (dest / "cleanup.log").write_text(value.stdout + value.stderr)
                    require(value.returncode == 0, "Dual-node cleanup failed")
                    require(not command(compose + ["ps", "--all", "-q"]).strip(),
                            "Dual-node test containers remain")
                except Exception as error:
                    summary["cleanup_errors"].append(str(error))
                    try:
                        ids = command([
                            "ps", "-a", "-q", "--filter",
                            "label=com.docker.compose.project=" + compose[2],
                        ]).split()
                        for cid in ids:
                            value = json.loads(command(["inspect", cid]))[0]
                            require(
                                value["Config"]["Labels"].get(
                                    "com.docker.compose.project") == compose[2],
                                "Unexpected cleanup project",
                            )
                        if ids:
                            command(["rm", "-f", *ids], timeout=60)
                        require(not command([
                            "ps", "-a", "-q", "--filter",
                            "label=com.docker.compose.project=" + compose[2],
                        ]).strip(), "Fallback cleanup left test containers")
                        summary["fallback_cleanup_succeeded"] = True
                    except Exception as fallback_error:
                        summary["cleanup_errors"].append(str(fallback_error))
            if baseline is not None:
                try:
                    summary["baseline_ric_after"] = identity(BASE_RIC)
                    require(summary["baseline_ric_after"] == baseline,
                            "Baseline RIC changed")
                except Exception as error:
                    summary["cleanup_errors"].append(str(error))
            if core_before is not None:
                try:
                    summary["core_after"] = {
                        name: identity(name) for name in core_before
                    }
                    require(summary["core_after"] == core_before,
                            "Core service identity changed")
                except Exception as error:
                    summary["cleanup_errors"].append(str(error))
            if summary["cleanup_errors"]:
                summary["passed"] = False
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Evidence retained: {dest}", flush=True)
    if not summary["passed"]:
        raise SystemExit(1)
    print("PASS: embedded asynchronous bidirectional online advisory; no control executed.")


if __name__ == "__main__":
    main()
