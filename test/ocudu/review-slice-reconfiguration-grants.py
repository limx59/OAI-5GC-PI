#!/usr/bin/env python3
"""Review per-slot DL grants around an offline slice reconfiguration."""
import argparse
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[2]
CASE = (
    "multi_slice_with_prio_slice_scheduler_test."
    "multi_ue_limited_to_max_rbs_reconf"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    helper = ROOT / "test/ocudu/review-slice-scheduler-evidence.py"
    require(helper.resolve().is_relative_to(ROOT) and helper.is_file(),
            "Missing or unexpected counter reviewer")
    runpy.run_path(str(helper))["review"](dest)
    lines = (dest / "test.log").read_text(errors="replace").splitlines()
    starts = [i for i, line in enumerate(lines)
              if re.match(r"\[\s*RUN\s*\]\s+" + re.escape(CASE) + r"\s*$", line)]
    ends = [i for i, line in enumerate(lines)
            if re.match(r"\[\s*OK\s*\]\s+" + re.escape(CASE) + r"\s+\(", line)]
    require(len(starts) == len(ends) == 1 and starts[0] < ends[0],
            "Ambiguous test boundaries")
    block = lines[starts[0] + 1:ends[0]]
    events = [i for i, line in enumerate(block)
              if "- Slice Reconfig: cell=0" in line]
    notices = [i for i, line in enumerate(block)
               if "Slice reconfiguration applied" in line]
    require(len(events) == len(notices) == 1 and notices[0] < events[0],
            "Missing or ambiguous reconfiguration boundary")

    header = re.compile(
        r"\[\s*(\d+)\.(\d+)\]\s+Slot decisions pci=1 .*?"
        r"\((\d+) PDSCH"
    )
    grant = re.compile(
        r"^- UE PDSCH: ue=(\d+) c-rnti=0x([0-9a-fA-F]+).*?"
        r"rb=\[(\d+)\.\.(\d+)\) symb=\[(\d+)\.\.(\d+)\)"
    )
    headers = [(i, header.search(line)) for i, line in enumerate(block)
               if header.search(line)]
    require(headers, "No slot decision records")
    rows = {"before": [], "after": []}
    seen = set()
    for number, (start, match) in enumerate(headers):
        count = int(match[3])
        if count == 0:
            continue
        phase = "before" if start < events[0] else "after"
        if len(rows[phase]) == 4:
            continue
        stop = headers[number + 1][0] if number + 1 < len(headers) else len(block)
        records = []
        for line in block[start + 1:stop]:
            if "UE PDSCH:" not in line:
                continue
            parsed = grant.search(line)
            require(parsed is not None, "Unparsed UE grant")
            ue = int(parsed[1])
            rnti = int(parsed[2], 16)
            lo, hi, symlo, symhi = map(int, parsed.groups()[2:])
            require(ue in (0, 1, 2) and rnti == 0x4601 + ue,
                    "Unexpected UE/RNTI mapping")
            require(0 <= lo < hi <= 51 and 0 <= symlo < symhi <= 14,
                    "Invalid grant interval")
            records.append((ue, lo, hi, symlo, symhi))
        require(len(records) == count,
                "Selected slot has missing UE grants or non-UE PDSCHs")
        slot = match[1] + "." + match[2]
        require(slot not in seen, "Duplicate selected slot")
        seen.add(slot)
        for i, a in enumerate(records):
            for b in records[i + 1:]:
                require(not (
                    max(a[1], b[1]) < min(a[2], b[2])
                    and max(a[3], b[3]) < min(a[4], b[4])
                ), "Overlapping UE allocations")
        by_ue = [sum(hi - lo for ue, lo, hi, _, _ in records if ue == index)
                 for index in range(3)]
        first, second = by_ue[0] + by_ue[1], by_ue[2]
        low, high, other_high = (10, 20, 51) if phase == "before" else (5, 15, 20)
        require(low <= first <= high and 0 < second <= other_high,
                "Per-slice grant budget violated in slot " + slot)
        rows[phase].append({
            "slot": slot, "ue_rbs": by_ue,
            "slice_rbs": [first, second],
        })

    for phase in rows:
        require(len(rows[phase]) == 4, "Insufficient slots: " + phase)
        require(all(sum(row["ue_rbs"][ue] for row in rows[phase]) > 0
                    for ue in range(3)),
                "A UE has no allocation in " + phase + " window")
    require(any(row["slice_rbs"][0] > 15 for row in rows["before"])
            and any(row["slice_rbs"][1] > 20 for row in rows["before"]),
            "No pre-change allocations exceeding new caps")
    return {
        "passed": True,
        "scope": "Offline DL raw-grant review; first four active slots per phase",
        "case": CASE,
        "ue_to_slice": {"0": "SST=1 SD=1", "1": "SST=1 SD=1",
                        "2": "SST=1 SD=2"},
        "boundary": "Scheduler Slice Reconfig event, cell=0",
        "windows": rows,
        "live_ran_validated": False,
        "multi_agent_control_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    dest = args.evidence.resolve()
    parent = (ROOT / "test/ocudu/.local/evidence").resolve()
    require(parent.is_relative_to(ROOT)
            and dest.is_relative_to(parent) and dest.is_dir(),
            "Unexpected evidence directory")
    output = dest / "reconfiguration-grant-review.json"
    require(not output.exists(), "Review output already exists")
    result = review(dest)
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print("SAVED:", output)


if __name__ == "__main__":
    main()
