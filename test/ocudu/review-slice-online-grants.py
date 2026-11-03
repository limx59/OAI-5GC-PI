#!/usr/bin/env python3
"""Review retained single-UE DL grants around online slice updates."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    def read(name):
        path = dest / name
        require(path.resolve().is_relative_to(dest) and path.is_file(),
                "Missing or unexpected evidence: " + name)
        return path.read_text(errors="strict")

    summary = json.loads(read("summary.json"))
    require(summary.get("passed") is True
            and summary.get("control_requests_sent") == 2
            and summary.get("cleanup_errors") == []
            and summary.get("baseline_before")
            == summary.get("baseline_after")
            and summary.get("test_before") == summary.get("test_after"),
            "Unexpected original test result")
    require(summary["configuration"]["slice"] == {
        "sst": 1, "sd": None,
        "min_prb_policy_ratio": 0, "max_prb_policy_ratio": 100,
    }, "Unexpected configured slice")
    config = read("config/gnb.yml")
    require(hashlib.sha256(config.encode()).hexdigest()
            == summary["configuration"]["generated_sha256"],
            "Generated configuration hash mismatch")

    header = re.compile(
        r"Slot decisions pci=1 .*?\((\d+) PDSCHs?, (\d+) PUSCHs?"
    )
    grant = re.compile(
        r"UE (PDSCH|PUSCH): ue=(\d+) c-rnti=(0x[0-9a-fA-F]+)"
        r".*?\brb=\[(\d+)\.\.(\d+)\)"
    )
    result = {
        "passed": False,
        "scope": "Retained single-UE DL per-slot grant cap and restoration",
        "cell_prbs": 51,
        "limited_prb_cap": 51 * 20 // 100,
        "phases": {},
        "ul_cap_effect_validated": False,
        "multi_agent_control_validated": False,
    }
    for phase, maximum in (("limited", 20), ("restored", 100)):
        before = read(f"gnb.{phase}.before.log")
        after = read(f"gnb.{phase}.after.log")
        require(after.startswith(before), "Log history mismatch")
        delta = after[len(before):]
        marker = "- Slice Reconfig: cell=0"
        require(delta.count(marker) == 1, "Expected one scheduler update")
        lines = delta.split(marker, 1)[1].splitlines()

        control = [
            json.loads(line)
            for line in read(f"control-{phase}.log").splitlines()
            if line.strip()
        ]
        requests = [r["payload"] for r in control if r.get("event") == "request"]
        responses = [r["payload"] for r in control if r.get("event") == "response"]
        require(len(requests) == len(responses) == 1,
                "Expected one request and response")
        require(requests[0] == {
            "cmd": "rrm_policy_ratio_set",
            "policies": {
                "resourceType": "PRB",
                "rRMPolicyMemberList": [{"plmn": "00101", "sst": 1}],
                "min_prb_policy_ratio": 0,
                "max_prb_policy_ratio": maximum,
            },
        }, "Unexpected control request")
        require(responses[0].get("cmd") == "rrm_policy_ratio_set"
                and "error" not in responses[0],
                "Unexpected control response")

        blocks = []
        current = None
        widths = {"PDSCH": [], "PUSCH": []}
        for line in lines:
            match = header.search(line)
            if match:
                current = {
                    "expected": list(map(int, match.groups())),
                    "seen": [0, 0], "dl_prbs": 0,
                }
                blocks.append(current)
                continue
            if "UE PDSCH:" not in line and "UE PUSCH:" not in line:
                continue
            match = grant.search(line)
            require(match is not None and current is not None,
                    "Unparsed or orphan UE grant")
            direction, ue, rnti, low, high = match.groups()
            low, high = int(low), int(high)
            require(ue == "0" and rnti.lower() == "0x4601"
                    and 0 <= low < high <= 51,
                    "Unexpected UE identity or RB interval")
            retry = re.search(r"\bnrtx=(\d+)\b", line)
            require(retry is not None and int(retry[1]) == 0,
                    "Retransmission requires separate analysis")
            width = high - low
            widths[direction].append(width)
            index = 0 if direction == "PDSCH" else 1
            current["seen"][index] += 1
            if direction == "PDSCH":
                lcids = re.findall(r"\blcid=(\d+):", line)
                require(lcids and set(lcids) == {"4"},
                        "Unexpected or unclassified DL logical channel")
                current["dl_prbs"] += width

        require(blocks and all(b["seen"] == b["expected"] for b in blocks),
                "Header/grant count mismatch or non-UE data allocation")
        require(widths["PDSCH"] and widths["PUSCH"],
                "Missing DL or UL grant evidence")
        dl_slots = [b["dl_prbs"] for b in blocks if b["seen"][0]]
        cap = 51 * maximum // 100
        require(all(value <= cap for value in dl_slots),
                "Observed DL per-slot allocation exceeds configured cap")
        if phase == "limited":
            require(10 in dl_slots, "Limited phase never reached 10 PRBs")
        else:
            require(any(value > 10 for value in dl_slots),
                    "Restored phase did not exceed the former cap")

        result["phases"][phase] = {
            "max_ratio": maximum,
            "dl_grants": len(widths["PDSCH"]),
            "dl_active_slots": len(dl_slots),
            "dl_max_prbs_per_slot": max(dl_slots),
            "dl_grant_width_histogram": dict(sorted(Counter(widths["PDSCH"]).items())),
            "ul_grants": len(widths["PUSCH"]),
            "ul_grant_width_histogram": dict(sorted(Counter(widths["PUSCH"]).items())),
            "all_grants_new_transmissions": True,
            "dl_lcid": 4,
        }
    result["passed"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    dest = args.evidence.resolve()
    require(dest.is_relative_to(ROOT / "test/ocudu/.local/evidence")
            and dest.is_dir(), "Unexpected evidence directory")
    target = dest / "online-grant-review.json"
    require(not target.exists(), "Review output already exists")
    result = review(dest)
    with target.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print("SAVED:", target)


if __name__ == "__main__":
    main()
