#!/usr/bin/env python3
"""Review retained default-fixture energy advice and simulated feedback."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    dest = dest.resolve()
    require(dest.is_relative_to(BASE.resolve()) and dest.is_dir(),
            "Unexpected evidence directory")

    def read(name, jsonl=False):
        path = dest / name
        require(path.resolve().is_relative_to(dest) and path.is_file(),
                "Missing or unexpected evidence: " + name)
        text = path.read_text()
        return ([json.loads(line) for line in text.splitlines()]
                if jsonl else json.loads(text))

    report = read("summary.json")
    summary = read("results/summary.json")
    advice = read("results/advisory.jsonl", True)
    events = read("results/simulation.jsonl", True)
    require(report.get("passed") is True and report.get("cleanup_errors") == [],
            "Original Compose run failed")
    container = report["container"]
    require(container["image"] == report["image"]["id"]
            and container["exit_code"] == 0
            and container["oom_killed"] is False
            and container["restarts"] == 0,
            "Unexpected container outcome")
    raw = (ROOT / "test/xapp/energy_samples.json").read_bytes()
    samples = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    require(summary == report["result"]
            and summary["input_sha256"] == digest
            and summary["completed"] is True
            and summary["observations"] == 6,
            "Summary or input provenance mismatch")
    require(len(samples) == len(advice) == len(events) == 6,
            "Unexpected record count")

    statuses = [
        "pending", "pending", "pending", "recommendation",
        "hold_energy_saving", "recommendation",
    ]
    actions = {3: "consider_energy_saving", 5: "restore_active_mode"}
    mode = "active"
    transitions = []
    recommendations = []
    for index, (sample, advisory, event) in enumerate(zip(samples, advice, events)):
        for record in (advisory, event):
            require(record["sequence"] == index + 1
                    and record["time_s"] == sample["time_s"],
                    "Record sequence or timestamp mismatch")
            require(record["executed"] is False
                    and record["real_control_executed"] is False
                    and record["power_saving_measured"] is False
                    and record["live_ocudu_metrics_validated"] is False
                    and record["coverage_measurement_validated"] is False
                    and record["source_time_is_simulated"] is True
                    and record["input_source"] == "explicit synthetic fixtures"
                    and record["input_sha256"] == digest,
                    "Invalid provenance or execution claim")
            require(record["status"] == statuses[index]
                    and record.get("action") == actions.get(index),
                    "Unexpected recommendation")
            if index <= 3:
                require(record.get("low_demand_duration_s") == index * 10,
                        "Incorrect low-demand confirmation duration")
        require(advisory["observed_mode"] == sample["observed_mode"]
                and event["input_observed_mode"] == sample["observed_mode"]
                and event["observed_mode"] == mode
                and event["simulation_mode_before"] == mode,
                "Broken simulation state continuity")
        next_mode = mode
        if index in actions:
            next_mode = "energy_saving" if index == 3 else "active"
            recommendations.append({
                "time_s": sample["time_s"], "action": actions[index],
            })
        require(event["simulation_mode_after"] == next_mode
                and event["applied_in_simulation"] is (next_mode != mode),
                "Incorrect simulated transition")
        if next_mode != mode:
            transitions.append({
                "time_s": sample["time_s"], "before": mode, "after": next_mode,
            })
        mode = next_mode

    require(summary["recommendations"] == recommendations
            and summary["simulated_transitions"] == transitions,
            "Summary differs from event records")
    require(summary["real_control_executed"] is False
            and summary["power_saving_measured"] is False
            and summary["live_ocudu_metrics_validated"] is False
            and summary["coverage_measurement_validated"] is False
            and summary["source_time_is_simulated"] is True
            and summary["input_source"] == "explicit synthetic fixtures",
            "Invalid summary scope claim")
    return {
        "passed": True,
        "scope": "Retained synthetic energy-advice and state-feedback evidence",
        "observations": 6,
        "simulated_transitions": transitions,
        "real_control_executed": False,
        "power_saving_measured": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.evidence), indent=2))
    print("Read-only review; original evidence unchanged.")


if __name__ == "__main__":
    main()
