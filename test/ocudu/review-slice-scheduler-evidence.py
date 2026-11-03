#!/usr/bin/env python3
"""Recalculate slice ratios from retained offline test counters."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_IMAGE = (
    "sha256:a6432f1ea245d94dc8f14b8325034feef36bef66ab142413d6489525f6b0b4cb"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    for name in ("summary.json", "results.xml", "test.log"):
        path = dest / name
        require(path.resolve().is_relative_to(dest) and path.is_file(),
                "Missing or unexpected evidence: " + name)

    summary = json.loads((dest / "summary.json").read_text())
    require(summary.get("passed") is True
            and summary.get("tests_passed") == 8
            and summary.get("cleanup_errors") == []
            and summary.get("network") == "none"
            and summary.get("control_requests_sent") == 0,
            "Unexpected original test result")
    require(summary.get("image", {}).get("id") == EXPECTED_IMAGE,
            "Unexpected test image")

    xml = ET.parse(dest / "results.xml").getroot()
    cases = list(xml.iter("testcase"))
    require(len(cases) == 8, "Expected eight XML test cases")
    for case in cases:
        require(case.get("status") == "run"
                and case.get("result") == "completed"
                and not any(case.find(tag) is not None
                            for tag in ("failure", "error", "skipped")),
                "Incomplete or failed XML test case")
    require(any(
        case.get("classname") == "multi_slice_dedicated_ul_rbs_test"
        and case.get("name") == "ul_dedicated_rbs_ratio_is_respected"
        for case in cases
    ), "Dedicated-ratio test missing")

    log = (dest / "test.log").read_text(errors="replace")
    ul = re.findall(
        r"UL RBs: 75%=(\d+) 25%=(\d+) total=(\d+) "
        r"ul_slots=(\d+) avg_prbs/ul_slot=([\d.]+) \(cell=([\d.]+)\)",
        log,
    )
    dl = re.findall(r"DL RBs: 75%=(\d+) 25%=(\d+)", log)
    require(len(ul) == 1 and len(dl) == 1,
            "Expected exactly one UL and one DL counter record")
    ul75, ul25, total, slots = map(int, ul[0][:4])
    logged_average, available = map(float, ul[0][4:])
    dl75, dl25 = map(int, dl[0])
    require(min(ul75, ul25, slots, dl75, dl25) > 0 and available > 0,
            "Missing traffic or invalid denominator")
    require(ul75 + ul25 == total, "UL counter sum mismatch")

    expected = 38 / 13
    tolerance = 0.15
    ul_ratio = ul75 / ul25
    dl_ratio = dl75 / dl25
    average = total / slots
    require(abs(average - logged_average) <= 0.051,
            "Logged rounded UL average disagrees with counters")
    require(abs(ul_ratio - expected) <= expected * tolerance,
            "UL ratio outside original test tolerance")
    require(abs(dl_ratio - expected) <= expected * tolerance,
            "DL ratio outside original test tolerance")
    require(abs(average - available) <= available * tolerance,
            "UL utilisation outside original test tolerance")

    return {
        "passed": True,
        "scope": "Offline logged-counter recalculation",
        "basis": "Retained aggregate counters; not a raw-grant recount",
        "configured_rb_budgets": [38, 13],
        "expected_ratio": expected,
        "relative_tolerance": tolerance,
        "accepted_ratio_interval": [
            expected * (1 - tolerance), expected * (1 + tolerance),
        ],
        "ul": {
            "slice_rbs": [ul75, ul25], "total_rbs": total,
            "slots_with_pusch": slots, "ratio": ul_ratio,
            "average_rbs_per_active_slot": average,
            "available_ul_rbs": available,
            "average_available_rb_utilisation": average / available,
        },
        "dl": {"slice_rbs": [dl75, dl25], "ratio": dl_ratio},
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
    output = dest / "counter-review.json"
    require(not output.exists(), "Review output already exists")
    result = review(dest)
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print("SAVED:", output)


if __name__ == "__main__":
    main()
