#!/usr/bin/env python3
"""Recompute actual DL slot allocations from retained closed-loop logs."""
import argparse
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"
HEADER = re.compile(
    r"^.*Slot decisions pci=1 .*?\((\d+) PDSCHs?, (\d+) PUSCHs?.*$",
    re.M,
)
GRANT = re.compile(
    r"UE (PDSCH|PUSCH): ue=(\d+) c-rnti=(0x[0-9a-fA-F]+)"
    r".*?\brb=\[(\d+)\.\.(\d+)\).*?\bnrtx=(\d+)\b"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    dest = dest.resolve()
    require(dest.is_relative_to(BASE.resolve()) and dest.is_dir(),
            "Unexpected evidence directory")

    def read(name):
        path = dest / name
        require(path.resolve().is_relative_to(dest) and path.is_file(),
                "Missing or unexpected evidence: " + name)
        return json.loads(path.read_text())

    summary = read("summary.json")
    require(summary.get("passed") is True
            and summary.get("control_requests_attempted") == 4
            and summary.get("control_replies_validated") == 4
            and summary.get("cleanup_errors") == [],
            "Original run failed or unexpected control count")
    for prefix in ("baseline", "test"):
        before = summary.get(prefix + "_before")
        require(before and before == summary.get(prefix + "_after"),
                "Process identities changed")
        require(all(v.get("running") is True
                    and v.get("oom_killed") is False for v in before.values()),
                "Unhealthy retained process")

    Policy = runpy.run_path(str(
        ROOT / "test/ocudu/slice_queue_policy.py"
    ))["QueuePolicy"]
    State = runpy.run_path(str(
        ROOT / "test/ocudu/slice_queue_control_state.py"
    ))["QueueControlState"]
    sources = {}
    for node, service in (("420", "gnb"), ("421", "gnb-2")):
        original = summary["test_before"][service]
        sources[node] = original["id"] + ":" + original["started"]
    policy = Policy(sources)
    state = State(100)
    maximum_age = 0
    executions = []
    for revision in range(1, 6):
        item = read(f"queue-decision.{revision}.json")
        now = item["decision_time_s"]
        require(set(item["reports"]) == set(sources),
                "Both node reports required")
        for node, report in item["reports"].items():
            require(
                item["trigger_sent_s"][node]
                <= report["trigger_received_s"]
                <= report["host_query_start_s"]
                < report["before_snapshot_received_s"]
                < report["host_query_end_s"]
                <= item["report_received_s"][node] <= now,
                "Invalid sampling/receipt timing",
            )
            require(report == summary["node_observations"][node][revision - 1],
                    "Saved observation mismatch")
            maximum_age = max(maximum_age, now - report["host_query_end_s"])
        decision = policy.evaluate(now, item["reports"])
        require(decision == item["result"], "Policy replay mismatch")
        action = read(f"queue-control.{revision}.json")
        plan = state.propose(revision, decision)
        require(plan == action["plan"], "Control plan mismatch")
        if plan is not None:
            require(action["executed"] is True, "Expected execution missing")
            outcomes = action["execution_result"]["attempt"]["node_results"]
            committed = state.complete(
                plan["generation"],
                {node: result["verified"] for node, result in outcomes.items()},
            )
            require(committed == action["execution_result"]["coordinator_result"],
                    "Commit replay mismatch")
            executions.append(state.max_ratio)
        else:
            require(action["executed"] is False, "Unexpected duplicate execution")
            expected_reason = (
                "already_committed" if decision["status"] == "confirmed"
                else "no_confirmed_recommendation"
            )
            require(action["reason"] == expected_reason, "Skip reason mismatch")
        require(action["committed_max_ratio"] == state.max_ratio,
                "Committed cap mismatch")
    require(executions == [20, 100] and state.pending is None,
            "Unexpected control sequence")

    results = []
    for revision, generation, ratio in ((2, 1, 20), (4, 2, 100)):
        action = read(f"queue-control.{revision}.json")
        require(action.get("executed") is True
                and action.get("committed_max_ratio") == ratio,
                "Expected committed action missing")
        execution = action["execution_result"]
        require(execution.get("status") == "committed"
                and execution["attempt"]["all_nodes_verified"] is True,
                "Execution not committed")
        for node in ("420", "421"):
            tag = f"live-generation{generation}.attempt1.{node}"
            outcome = execution["attempt"]["node_results"][node]
            require(outcome.get("verified") is True
                    and outcome.get("generation") == generation
                    and outcome.get("max_ratio") == ratio
                    and outcome.get("evidence_tag") == tag,
                    "Unexpected node execution record")
            before = read(f"gnb.{tag}.before.json")
            after = read(f"gnb.{tag}.after.json")
            require(set(before) == set(after) == {"stdout", "stderr"},
                    "Unexpected log streams")
            require(all(after[k].startswith(before[k]) for k in before),
                    "Scheduler history changed")
            delta = "\n".join(after[k][len(before[k]):] for k in before)
            marker = "- Slice Reconfig: cell=0"
            require(delta.count(marker) == 1,
                    "Expected one scheduler update")
            segment = delta.split(marker, 1)[1]
            headers = list(HEADER.finditer(segment))
            totals = []
            parsed = 0
            for index, match in enumerate(headers):
                end = (headers[index + 1].start()
                       if index + 1 < len(headers) else len(segment))
                records = GRANT.findall(segment[match.end():end])
                counts = {
                    direction: sum(r[0] == direction for r in records)
                    for direction in ("PDSCH", "PUSCH")
                }
                require(counts["PDSCH"] == int(match[1])
                        and counts["PUSCH"] == int(match[2]),
                        "Incomplete scheduler slot")
                total = 0
                for direction, ue, rnti, low, high, nrtx in records:
                    parsed += 1
                    low, high = int(low), int(high)
                    require(ue == "0" and rnti.lower() == "0x4601"
                            and nrtx == "0" and 0 <= low < high <= 51,
                            "Unexpected grant identity or allocation")
                    if direction == "PDSCH":
                        total += high - low
                if counts["PDSCH"]:
                    totals.append(total)
            require(parsed == len(re.findall(
                r"UE (?:PDSCH|PUSCH):", segment
            )), "Grant outside parsed slot blocks")
            require(totals, "Missing actual DL grants")
            if ratio == 20:
                require(max(totals) <= 10 and 10 in totals,
                        "Actual DL cap not demonstrated")
            else:
                require(max(totals) > 10,
                        "Actual DL restoration not demonstrated")
            recomputed = {
                "active_slots": len(totals),
                "max_prbs_per_slot": max(totals),
                "slots_above_10": sum(v > 10 for v in totals),
            }
            require(recomputed == outcome["dl_grant_check"],
                    "Saved grant statistics differ from raw logs")
            results.append({
                "generation": generation, "node": node,
                "max_ratio": ratio, **recomputed,
            })

    final = read("queue-control.5.json")
    require(final.get("executed") is False
            and final.get("reason") == "already_committed"
            and final.get("plan") is None
            and final.get("committed_max_ratio") == 100,
            "Repeated-state suppression missing")
    return {
        "passed": True,
        "scope": "Live queue decisions, state replay and raw DL grants",
        "maximum_report_age_s": maximum_age,
        "nodes": results,
        "e2_control_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    for dest in args.evidence:
        result = review(dest)
        print("PASS:", dest.name)
        for item in result["nodes"]:
            print(json.dumps(item))
    print("Read-only review; original evidence unchanged.")


if __name__ == "__main__":
    main()
