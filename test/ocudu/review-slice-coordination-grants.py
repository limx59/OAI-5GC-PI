#!/usr/bin/env python3
"""Review fixture-driven dual-node decisions and actual DL grants."""
import argparse
from collections import Counter
import hashlib
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
    hashes = {}

    def read(name, as_json=True):
        path = dest / name
        require(path.resolve().is_relative_to(dest) and path.is_file(),
                "Missing or unexpected evidence: " + name)
        raw = path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        text = raw.decode()
        return json.loads(text) if as_json else text

    summary = read("summary.json")
    require(summary.get("passed") is True
            and summary.get("demand_source") == "explicit synthetic fixtures"
            and summary.get("control_requests_attempted") == 8
            and summary.get("control_replies_validated") == 8
            and summary.get("cleanup_errors") == [],
            "Unexpected original online result")
    for prefix in ("baseline", "test"):
        before = summary.get(prefix + "_before")
        require(before and before == summary.get(prefix + "_after"),
                "Process identity mismatch: " + prefix)
        require(all(value["running"] and not value["oom_killed"]
                    for value in before.values()),
                "Unhealthy process: " + prefix)
    test = summary["test_before"]
    require(set(test) == {"gnb", "gnb-2", "nrue", "nrue-2"},
            "Unexpected test services")
    require(all(test[name]["image"] ==
            "sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b"
            for name in ("gnb", "gnb-2")), "Unexpected gNB image")
    configuration = summary["configuration"]
    require(configuration["node_ids"] == [420, 421]
            and configuration["e2_enabled"] is False
            and configuration["slice"] == {
                "sst": 1, "sd": None,
                "min_prb_policy_ratio": 0,
                "max_prb_policy_ratio": 100,
            }, "Unexpected slice configuration")

    expected = (
        ("node420-high", (80, 10), 20),
        ("both-low-1", (10, 10), 100),
        ("node421-high", (10, 80), 20),
        ("both-low-2", (10, 10), 100),
    )
    require([p["label"] for p in summary["phases"]] ==
            [p[0] for p in expected], "Unexpected phase sequence")
    Coordinator = runpy.run_path(str(
        ROOT / "test/ocudu/slice_coordination_policy.py"
    ))["SliceCoordinator"]
    coordinator = Coordinator()
    results = []
    for phase, (label, demands, ratio) in zip(summary["phases"], expected):
        require(phase["max_ratio"] == ratio,
                "Unexpected phase ratio")
        for pair in range(2):
            record = read(f"decision.{label}.{pair}.json")
            reports = record["input"]
            require(set(reports) == {"420", "421"}
                    and tuple(reports[n]["demand_prb_percent"]
                              for n in ("420", "421")) == demands,
                    "Unexpected fixture demand")
            now = max(item["receipt_time_s"] for item in reports.values())
            decision = coordinator.evaluate(now, reports)
            require(decision == record["result"],
                    "Recorded decision differs from replay")
            require(decision["status"] ==
                    ("pending_confirmation" if pair == 0 else "plan_ready"),
                    "Unexpected decision status")
        plan = decision["plan"]
        nodes = {}
        for node in ("420", "421"):
            control = [
                json.loads(line)
                for line in read(f"control.{label}.{node}.log", False).splitlines()
                if line.startswith("{")
            ]
            requests = [r["payload"] for r in control
                        if r.get("event") == "request"]
            replies = [r["payload"] for r in control
                       if r.get("event") == "response"]
            require(len(requests) == len(replies) == 1,
                    "Unexpected request or reply count")
            require(requests[0] == {
                "cmd": "rrm_policy_ratio_set",
                "policies": {
                    "resourceType": "PRB",
                    "rRMPolicyMemberList": [{"plmn": "00101", "sst": 1}],
                    "min_prb_policy_ratio": 0,
                    "max_prb_policy_ratio": ratio,
                },
            }, "Unexpected control payload")
            require(replies[0].get("cmd") == "rrm_policy_ratio_set"
                    and "error" not in replies[0]
                    and replies[0].get("timestamp"),
                    "Invalid control reply")
            ping = read(f"ping.{label}.{node}.log", False)
            require(re.search(
                r"5 packets transmitted, 5 received, 0% packet loss", ping
            ), "Strict ping did not pass")

            before = read(f"gnb.{label}.{node}.before.json")
            after = read(f"gnb.{label}.{node}.after.json")
            require(set(before) == set(after) == {"stdout", "stderr"}
                    and all(after[k].startswith(before[k]) for k in before),
                    "Log history mismatch")
            delta = "\n".join(after[k][len(before[k]):] for k in before)
            marker = "- Slice Reconfig: cell=0"
            require(delta.count(marker) == 1,
                    "Expected one scheduler update")
            tail = delta.split(marker, 1)[1]
            headers = list(HEADER.finditer(tail))
            widths = Counter()
            totals = []
            parsed = 0
            for i, match in enumerate(headers):
                end = headers[i + 1].start() if i + 1 < len(headers) else len(tail)
                records = GRANT.findall(tail[match.end():end])
                counts = Counter(r[0] for r in records)
                require(counts["PDSCH"] == int(match[1])
                        and counts["PUSCH"] == int(match[2]),
                        "Incomplete or unparsed slot")
                dl_total = 0
                for direction, ue, rnti, low, high, nrtx in records:
                    parsed += 1
                    low, high = int(low), int(high)
                    require(ue == "0" and rnti.lower() == "0x4601",
                            "Unexpected UE identity")
                    require(nrtx == "0", "Retransmission requires separate review")
                    require(0 <= low < high <= 51, "Unexpected RB range")
                    if direction == "PDSCH":
                        widths[high - low] += 1
                        dl_total += high - low
                if counts["PDSCH"]:
                    totals.append(dl_total)
            require(parsed == len(re.findall(r"UE (?:PDSCH|PUSCH):", tail)),
                    "Grant outside parsed slot blocks")
            require(totals, "Missing DL grant evidence")
            if ratio == 20:
                require(max(totals) <= 10, "DL allocation exceeds limited cap")
                require(10 in totals, "Limited phase did not reach cap")
            else:
                require(max(totals) > 10, "Restoration did not exceed former cap")
            nodes[node] = {
                "dl_active_slots": len(totals),
                "dl_max_prbs_per_slot": max(totals),
                "dl_slots_above_10": sum(v > 10 for v in totals),
                "dl_grant_width_histogram": dict(sorted(widths.items())),
            }
        committed = coordinator.complete(
            plan["generation"], {"420": True, "421": True}
        )
        require(committed == phase["coordinator_result"]
                and phase["generation"] == plan["generation"]
                and phase["node_outcomes"] == {"420": True, "421": True},
                "Unexpected coordinator completion")
        results.append({"phase": label, "max_ratio": ratio, "nodes": nodes})
    return {
        "passed": True,
        "scope": "Synthetic-demand coordinated WebSocket DL cap/restoration",
        "cell_prbs_per_node": 51,
        "limited_prb_cap_per_node": 10,
        "phases": results,
        "live_demand_reporting_validated": False,
        "ul_cap_effect_validated": False,
        "failure_recovery_validated": False,
        "e2_control_validated": False,
        "evidence_sha256": hashes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    result = review(args.evidence)
    path = args.evidence.resolve() / "coordination-grant-review.json"
    with path.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items()
                      if k != "evidence_sha256"}, indent=2))
    print("SAVED:", path)


if __name__ == "__main__":
    main()
