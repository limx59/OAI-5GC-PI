#!/usr/bin/env python3
"""Replay energy observations with simulated mode feedback; no E2 control."""

import argparse
import json
from pathlib import Path

from xapp_energy_policy import EnergyPolicy

HERE = Path(__file__).resolve().parent


def simulate(samples, initial_mode="active"):
    if not isinstance(samples, list) or not samples:
        raise ValueError("Input must be a nonempty JSON array.")
    if initial_mode not in ("active", "energy_saving"):
        raise ValueError("Invalid initial mode.")

    # Validate the original observations before replaying with mode feedback.
    validator = EnergyPolicy()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Each observation must be a JSON object.")
        validator.evaluate(sample)

    policy = EnergyPolicy()
    mode = initial_mode
    events = []
    for sample in samples:
        observation = dict(sample)
        observation["observed_mode"] = mode
        decision = policy.evaluate(observation)
        before = mode
        applied = False
        if decision["status"] == "recommendation":
            action = decision.get("action")
            if action == "consider_energy_saving":
                mode = "energy_saving"
            elif action == "restore_active_mode":
                mode = "active"
            else:
                raise ValueError(f"Unknown energy action: {action}")
            applied = mode != before

        events.append({
            **decision,
            "input_observed_mode": sample["observed_mode"],
            "simulation_mode_before": before,
            "simulation_mode_after": mode,
            "applied_in_simulation": applied,
            "executed": False,
        })
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", nargs="?", type=Path,
        default=HERE / "energy_samples.json",
    )
    parser.add_argument(
        "--initial-mode", choices=("active", "energy_saving"),
        default="active",
    )
    args = parser.parse_args()
    try:
        samples = json.loads(args.input.read_text(encoding="utf-8"))
        events = simulate(samples, args.initial_mode)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    for event in events:
        print(json.dumps(event), flush=True)


if __name__ == "__main__":
    main()
