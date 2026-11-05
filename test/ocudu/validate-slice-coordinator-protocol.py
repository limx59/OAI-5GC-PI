#!/usr/bin/env python3
"""Exercise coordinator JSON-line protocol using a local child process."""
import json
from pathlib import Path
import select
import subprocess
import sys
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    worker = Path(__file__).with_name("slice-coordinator.py")
    process = subprocess.Popen(
        [sys.executable, "-B", str(worker)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    request_id = 0
    sources = {"420": "source-420", "421": "source-421"}

    def call(operation, expected=True, **fields):
        nonlocal request_id
        request_id += 1
        process.stdin.write(json.dumps({
            "request_id": request_id, "operation": operation, **fields
        }) + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 5)
        require(ready, "Coordinator response timeout")
        response = json.loads(process.stdout.readline())
        require(response["request_id"] == request_id
                and response["passed"] is expected,
                "Unexpected protocol response: " + str(response))
        return response

    def reports(revision, value):
        end = time.monotonic() - 0.00001
        return {
            node: {
                "node_id": node, "source_instance": source,
                "revision": revision,
                "host_query_start_s": end - 0.00001,
                "host_query_end_s": end,
                "queue_unit": "bytes",
                "prb_demand_percent_established": False,
                "samples": [{"pending_dl_bytes_after_grant": value}],
                "sample_count": 1, "observation_status": "observed",
                "queue_statistics": {
                    "minimum": value, "maximum": value,
                    "positive_samples": int(value > 0),
                },
            }
            for node, source in sources.items()
        }

    try:
        call("status", expected=False)
        call("initialize", sources=sources, initial_max_ratio=100)
        call("initialize", expected=False,
             sources=sources, initial_max_ratio=100)
        call("evaluate", expected=False, revision=True, reports=reports(1, 40000))
        first = call("evaluate", revision=1, reports=reports(1, 40000))
        require(first["result"]["decision"]["confirmations"] == 1,
                "Invalid request consumed confirmation state")
        second = call("evaluate", revision=2, reports=reports(2, 40000))
        require(second["result"]["plan"]["generation"] == 1,
                "Limitation plan missing")
        call("evaluate", expected=False, revision=3, reports=reports(3, 0))
        call("complete", expected=False, generation=1,
             node_outcomes={"420": True, "421": False})
        status = call("status")
        require(status["committed_max_ratio"] == 100
                and status["pending_plan"] is not None,
                "Partial failure incorrectly committed")
        call("complete", generation=1,
             node_outcomes={"420": True, "421": True})
        call("evaluate", revision=3, reports=reports(3, 0))
        restored = call("evaluate", revision=4, reports=reports(4, 0))
        require(restored["result"]["plan"]["generation"] == 2,
                "Restoration plan missing")
        call("complete", generation=2,
             node_outcomes={"420": True, "421": True})
        duplicate = call("evaluate", revision=5, reports=reports(5, 0))
        require(duplicate["result"]["plan"] is None
                and duplicate["result"]["skip_reason"] == "already_committed",
                "Repeated-state suppression missing")
        stale = reports(6, 0)
        for report in stale.values():
            report["host_query_start_s"] -= 8
            report["host_query_end_s"] -= 8
        call("evaluate", expected=False, revision=6, reports=stale)
        call("evaluate", revision=6, reports=reports(6, 0))
        process.stdin.close()
        process.wait(timeout=5)
        require(process.returncode == 0, "Coordinator failed on EOF")
        print("PASS: initialization, version guard, limitation and restoration.")
        print("PASS: partial-failure blocking, reconciliation and deduplication.")
        print("PASS: stale rejection without consuming valid revision; clean EOF.")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
