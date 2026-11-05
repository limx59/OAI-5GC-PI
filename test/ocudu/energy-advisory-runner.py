#!/usr/bin/env python3
"""Record fixture-based energy advice and simulated feedback; no real control."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/xapp"))
from xapp_energy_policy import EnergyPolicy
from xapp_energy_simulator import simulate


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    samples = json.loads(raw)
    require(isinstance(samples, list) and 1 <= len(samples) <= 1000,
            "Expected 1..1000 fixture observations")
    fields = {
        "time_s", "demand_ratio", "observed_mode",
        "active_ues", "neighbor_coverage_confirmed",
    }
    for item in samples:
        require(isinstance(item, dict) and set(item) == fields,
                "Unexpected observation fields")
        for key in ("time_s", "demand_ratio"):
            value = item[key]
            require(type(value) in (int, float) and math.isfinite(value),
                    "Expected finite numeric fixture field: " + key)

    # Validate the complete sequence before creating result files.
    policy = EnergyPolicy()
    advice = [policy.evaluate(item) for item in samples]
    events = simulate(samples)
    require(all(item["executed"] is False for item in advice + events),
            "Unexpected real execution claim")

    output = args.output_dir.resolve()
    require(output.is_dir(), "Output directory must already exist")
    names = ("advisory.jsonl", "simulation.jsonl", "summary.json")
    require(not any((output / name).exists() for name in names),
            "Result output already exists")

    provenance = {
        "input_source": "explicit synthetic fixtures",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "live_ocudu_metrics_validated": False,
        "coverage_measurement_validated": False,
        "source_time_is_simulated": True,
        "real_control_executed": False,
        "power_saving_measured": False,
    }
    for name, records in (
        ("advisory.jsonl", advice),
        ("simulation.jsonl", events),
    ):
        with (output / name).open("x") as stream:
            (output / name).chmod(0o600)
            for index, record in enumerate(records, 1):
                stream.write(json.dumps({
                    "sequence": index, **record, **provenance,
                }) + "\n")

    transitions = [
        {
            "time_s": event["time_s"],
            "before": event["simulation_mode_before"],
            "after": event["simulation_mode_after"],
        }
        for event in events if event["applied_in_simulation"]
    ]
    summary = {
        "completed": True,
        "scope": "Energy advisory and state-feedback simulation only",
        "observations": len(samples),
        "recommendations": [
            {"time_s": item["time_s"], "action": item["action"]}
            for item in advice if item["status"] == "recommendation"
        ],
        "simulated_transitions": transitions,
        **provenance,
    }
    with (output / "summary.json").open("x") as stream:
        (output / "summary.json").chmod(0o600)
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
