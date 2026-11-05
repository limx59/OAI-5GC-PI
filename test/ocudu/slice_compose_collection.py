#!/usr/bin/env python3
"""Collect triggered node reports and evaluate them at real consumption time."""
import json
from pathlib import Path
import runpy
import time



def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def collect(agents, sources, rounds, on_sampling_ready, retain, remote):
    """Use {node: (Popen, JSONL path)}; caller owns process cleanup.

    Both agents must have emitted agent_ready and use --step-input.
    on_sampling_ready starts the workload after both first snapshots exist.
    retain(name, object) saves private evidence without printing raw samples.
    """
    require(set(agents) == set(sources) == {"420", "421"},
            "Expected two node agents")
    require(type(rounds) is int and 1 <= rounds <= 10,
            "Invalid collection round count")
    remote.initialize(sources)
    decisions = []

    def records(node):
        process, path = agents[node]
        parsed = []
        for line in path.read_text().splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            require(isinstance(value, dict), "Invalid agent record")
            require(value.get("event") != "observation_error",
                    "Node agent reported an observation error: " + node)
            parsed.append(value)
        return parsed

    for revision in range(1, rounds + 1):
        trigger_times = {}
        for node, (process, path) in agents.items():
            require(process.poll() is None and process.stdin is not None,
                    "Node agent unavailable for trigger")
            trigger_times[node] = time.monotonic()
            process.stdin.write(json.dumps({"revision": revision}) + "\n")
            process.stdin.flush()

        pair = {}
        receipt_times = {}
        sampling_announced = revision != 1
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            first_ready = set()
            for node, (process, path) in agents.items():
                items = records(node)
                if any(item.get("event") == "observation_ready"
                       and item.get("node_id") == node
                       and item.get("source_instance") == sources[node]
                       for item in items):
                    first_ready.add(node)
                matches = [
                    item for item in items
                    if item.get("event") == "node_observation"
                    and item.get("revision") == revision
                ]
                require(len(matches) <= 1, "Duplicate node report")
                if matches and node not in pair:
                    report = matches[0]
                    require(report.get("sampling_mode") == "coordinator_triggered"
                            and report.get("host_query_times_are_replay_fixtures")
                            is False,
                            "Unexpected sampling mode")
                    trigger = report.get("trigger_received_s")
                    start = report.get("host_query_start_s")
                    before_received = report.get("before_snapshot_received_s")
                    end = report.get("host_query_end_s")
                    require(all(type(v) in (int, float) for v in (
                        trigger, start, before_received, end
                    )) and trigger_times[node] <= trigger <= start
                            < before_received < end,
                            "Invalid triggered observation timing")
                    pair[node] = report
                    receipt_times[node] = time.monotonic()
                require(process.poll() in (None, 0),
                        "Node agent process failed: " + node)

            if not sampling_announced and first_ready == set(agents):
                on_sampling_ready()
                sampling_announced = True
            if set(pair) == set(agents) and sampling_announced:
                break
            time.sleep(0.05)

        require(set(pair) == set(agents) and sampling_announced,
                "Triggered report collection timed out")
        now = time.monotonic()
        # No synthetic replay clock and no relaxed age threshold.
        request_started = now
        response = remote.evaluate(revision, pair)
        received = time.monotonic()
        now = response["result"]["decision_time_s"]
        require(request_started <= now <= received,
                "Coordinator decision clock differs from host clock")
        result = response["result"]["decision"]
        evidence = {
            "coordinator_plan": response["result"]["plan"],
            "coordinator_request_started_s": request_started,
            "coordinator_response_received_s": received,
            "revision": revision,
            "trigger_sent_s": trigger_times,
            "report_received_s": receipt_times,
            "decision_time_s": now,
            "reports": pair,
            "result": result,
            "control_requests_sent": 0,
        }
        retain(f"queue-decision.{revision}.json", evidence)
        decisions.append({
            "revision": revision,
            "decision_time_s": now,
            "result": result,
        })
    return decisions
