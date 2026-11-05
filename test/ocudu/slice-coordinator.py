#!/usr/bin/env python3
"""Run a laboratory queue coordinator over a bounded JSON-lines interface.

The caller executes plans and supplies independently verified node outcomes.
This process sends no network controls. State does not survive restart.
"""
import argparse
import json
from pathlib import Path
import runpy
import sys
import time

HERE = Path(__file__).resolve().parent
Policy = runpy.run_path(str(HERE / "slice_queue_policy.py"))["QueuePolicy"]
State = runpy.run_path(str(
    HERE / "slice_queue_control_state.py"
))["QueueControlState"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    policy = state = None
    last_request = 0
    while True:
        raw = sys.stdin.readline(8_388_609)
        if not raw:
            return 0
        require(len(raw) <= 8_388_608 and raw.endswith("\n"),
                "Oversized or incomplete coordinator request")
        request_id = None
        try:
            request = json.loads(raw)
            require(isinstance(request, dict), "Expected request object")
            request_id = request.get("request_id")
            require(type(request_id) is int
                    and last_request < request_id <= 100,
                    "Invalid or duplicate request ID")
            last_request = request_id
            operation = request.get("operation")
            if operation == "initialize":
                require(policy is None, "Coordinator already initialized")
                candidate_policy = Policy(request["sources"])
                candidate_state = State(request["initial_max_ratio"])
                policy, state = candidate_policy, candidate_state
                result = {"status": "initialized"}
            else:
                require(policy is not None, "Coordinator not initialized")
                if operation == "evaluate":
                    require(state.pending is None,
                            "Pending execution requires reconciliation")
                    revision = request["revision"]
                    require(type(revision) is int
                            and revision > state.last_revision,
                            "Invalid decision revision")
                    reports = request["reports"]
                    require(isinstance(reports, dict)
                            and set(reports) == set(state.nodes)
                            and all(isinstance(r, dict)
                                    and type(r.get("revision")) is int
                                    and r["revision"] == revision
                                    for r in reports.values()),
                            "Report and decision revisions differ")
                    now = time.monotonic()
                    decision = policy.evaluate(now, reports)
                    plan = state.propose(revision, decision)
                    result = {
                        "decision_time_s": now,
                        "decision": decision,
                        "plan": plan,
                        "skip_reason": (
                            "already_committed"
                            if plan is None and decision["status"] == "confirmed"
                            else "no_confirmed_recommendation"
                            if plan is None else None
                        ),
                    }
                elif operation == "complete":
                    result = state.complete(
                        request["generation"], request["node_outcomes"]
                    )
                elif operation == "status":
                    result = {"status": "state"}
                else:
                    raise ValueError("Unknown coordinator operation")
            response = {
                "request_id": request_id,
                "passed": True,
                "result": result,
                "committed_max_ratio": state.max_ratio,
                "pending_plan": state.pending,
                "control_requests_sent": 0,
            }
        except (ValueError, KeyError, TypeError) as error:
            response = {
                "request_id": request_id,
                "passed": False,
                "error": str(error),
                "control_requests_sent": 0,
            }
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
