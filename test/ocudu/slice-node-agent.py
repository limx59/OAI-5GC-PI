#!/usr/bin/env python3
"""Report actual grant-conditioned DL queues from one laboratory gNB."""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import select
import sys
import time

OBSERVE = runpy.run_path(str(
    Path(__file__).with_name("slice_node_observation.py")
))["observe"]
IMAGE = "sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def docker(args):
    result = subprocess.run(
        (["docker"] if os.environ.get("SLICE_AGENT_DOCKER_DIRECT") == "1"
         else ["sudo", "docker"]) + args,
        capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=20,
    )
    require(result.returncode == 0, "Docker operation failed: " + args[0])
    return result


def identity(container, node):
    item = json.loads(docker(["inspect", container]).stdout)[0]
    labels = item["Config"].get("Labels") or {}
    service = "gnb" if node == "420" else "gnb-2"
    address = "172.22.0.160" if node == "420" else "172.22.0.164"
    require(labels.get("com.docker.compose.service") == service,
            "Container service does not match requested node")
    require(labels.get("com.docker.compose.project", "").startswith(
        "ocudu-slice-coord-"
    ), "Container is outside the coordination laboratory")
    require(item["Image"] == IMAGE, "Unexpected gNB image")
    require(item["State"]["Running"]
            and not item["State"]["OOMKilled"],
            "gNB process is not healthy")
    require(any(
        value.get("IPAddress") == address
        for value in item["NetworkSettings"]["Networks"].values()
    ), "Unexpected node address")
    return {
        "container_id": item["Id"],
        "started": item["State"]["StartedAt"],
        "pid": item["State"]["Pid"],
        "restarts": item["RestartCount"],
        "image": item["Image"],
    }


def snapshot(container):
    result = docker(["logs", container])
    return {"stdout": result.stdout, "stderr": result.stderr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=("420", "421"), required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--reports", type=int, default=2)
    parser.add_argument("--sample-seconds", type=float, default=3)
    parser.add_argument("--step-input", action="store_true",
                        help="Require one JSON trigger per report on stdin")
    args = parser.parse_args()
    require(1 <= args.reports <= 10, "Report count outside laboratory bound")
    require(1 <= args.sample_seconds <= 10, "Invalid sampling interval")
    require(re.fullmatch(r"[0-9a-f]{12,64}", args.container) is not None,
            "Expected a Docker container ID")

    initial = identity(args.container, args.node)
    configuration = docker([
        "exec", args.container, "cat", "/etc/ocudu/gnb.yml",
    ]).stdout
    matches = re.findall(r"(?m)^gnb_id:\s*(\d+)\s*$", configuration)
    require(matches == [args.node], "Configured gNB identity mismatch")
    instance = initial["container_id"] + ":" + initial["started"]

    if args.step_input:
        print(json.dumps({
            "event": "agent_ready",
            "node_id": args.node,
            "source_instance": instance,
        }), flush=True)

    for revision in range(1, args.reports + 1):
        trigger_received = None
        if args.step_input:
            ready, _, _ = select.select([sys.stdin], [], [], 45)
            require(bool(ready), "Sampling trigger timed out")
            raw = sys.stdin.readline(4097)
            require(raw.endswith("\n") and len(raw) <= 4096,
                    "Missing or oversized sampling trigger")
            trigger = json.loads(raw)
            require(isinstance(trigger, dict)
                    and set(trigger) == {"revision"}
                    and type(trigger["revision"]) is int
                    and trigger["revision"] == revision,
                    "Unexpected sampling trigger revision")
            trigger_received = time.monotonic()
        start = time.monotonic()
        before = snapshot(args.container)
        before_received = time.monotonic()
        if revision == 1:
            print(json.dumps({
                "event": "observation_ready",
                "node_id": args.node,
                "source_instance": instance,
            }), flush=True)
        time.sleep(args.sample_seconds)
        after = snapshot(args.container)
        end = time.monotonic()
        require(identity(args.container, args.node) == initial,
                "gNB process instance changed during observation")
        report = OBSERVE(
            args.node, instance, revision, before, after, start, end
        )
        report["event"] = "node_observation"
        report["sampling_mode"] = (
            "coordinator_triggered" if args.step_input else "autonomous"
        )
        report["trigger_received_s"] = trigger_received
        report["before_snapshot_received_s"] = before_received
        report["source_identity"] = initial
        report["host_query_times_are_replay_fixtures"] = False
        report["policy_input_established"] = False
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({
            "event": "observation_error",
            "error": str(error),
            "control_requests_sent": 0,
        }), flush=True)
        raise SystemExit(1)
