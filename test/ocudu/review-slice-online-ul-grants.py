#!/usr/bin/env python3
"""Review retained single-UE TCP UL grants across slice quota changes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"

HEADER = re.compile(
    r"^.*Slot decisions pci=1 .*?\(\d+ PDSCHs?, (\d+) PUSCHs?.*$",
    re.M,
)
GRANT = re.compile(
    r"UE PUSCH: ue=(\d+) c-rnti=(0x[0-9a-fA-F]+)"
    r".*?\brb=\[(\d+)\.\.(\d+)\).*?\bnrtx=(\d+)\b"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    dest = dest.resolve()
    require(dest.is_relative_to(BASE.resolve()) and dest.is_dir(),
            "Evidence outside repository evidence directory")

    def read(name):
        path = dest / name
        require(path.resolve().is_relative_to(dest) and path.is_file(),
                "Missing or unexpected evidence: " + name)
        return path.read_text(errors="strict")

    summary = json.loads(read("summary.json"))
    require(summary.get("passed") is True
            and summary.get("transport") == "TCP"
            and summary.get("control_requests_sent") == 2
            and summary.get("cleanup_errors") == [],
            "Unexpected original TCP test result")

    results = {}
    for phase in ("baseline", "limited", "restored"):
        before = read(f"gnb.ul-{phase}.before-load.log")
        after = read(f"gnb.ul-{phase}.after-load.log")
        require(after.startswith(before), "Log history mismatch: " + phase)

        headers = list(HEADER.finditer(after))
        widths = Counter()
        totals = []
        checked = 0

        for index, match in enumerate(headers):
            if match.start() < len(before):
                continue
            end = (headers[index + 1].start()
                   if index + 1 < len(headers) else len(after))
            block = after[match.end():end]
            records = GRANT.findall(block)
            require(len(records) == int(match.group(1))
                    and block.count("UE PUSCH:") == len(records),
                    "Incomplete PUSCH parsing: " + phase)
            checked += 1
            total = 0
            for ue, rnti, low, high, nrtx in records:
                low, high = int(low), int(high)
                require(ue == "0" and int(rnti, 16) == 0x4601,
                        "Unexpected UE identity: " + phase)
                require(0 <= low < high <= 51,
                        "Unexpected RB range: " + phase)
                require(int(nrtx) == 0,
                        "Retransmission requires separate review: " + phase)
                width = high - low
                widths[width] += 1
                total += width
            require(total <= 51, "UL allocation exceeds cell size")
            if records:
                totals.append(total)

        require(checked > 0 and totals, "Missing UL grants: " + phase)
        if phase == "limited":
            require(max(totals) <= 10,
                    "Observed UL per-slot allocation exceeds configured cap")
            require(10 in totals, "Limited phase did not reach configured cap")
        else:
            require(max(totals) > 10,
                    phase + " phase did not exceed the limited cap")

        results[phase] = {
            "checked_slot_headers": checked,
            "pusch_grants": sum(widths.values()),
            "active_ul_slots": len(totals),
            "max_prbs_per_logged_ul_slot": max(totals),
            "slots_above_limited_cap": sum(value > 10 for value in totals),
            "slots_at_limited_cap": totals.count(10),
            "grant_width_histogram": dict(sorted(widths.items())),
            "all_grants_new_transmissions": True,
        }

    return {
        "passed": True,
        "scope": "Retained single-UE TCP UL per-slot cap and restoration",
        "cell_prbs": 51,
        "limited_max_ratio": 20,
        "limited_prb_cap": 10,
        "phases": results,
        "ul_cap_effect_validated": True,
        "udp_failure_resolved": False,
        "multi_agent_control_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    result = review(args.evidence)
    output = args.evidence.resolve() / "online-ul-grant-review.json"
    text = json.dumps(result, indent=2) + "\n"
    with output.open("x") as stream:
        stream.write(text)
    print(text, end="")
    print("SAVED:", output)


if __name__ == "__main__":
    main()
