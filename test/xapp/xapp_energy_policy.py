#!/usr/bin/env python3
"""Recommend cell energy-mode changes from simulated observations."""

import argparse
import json
import math
from pathlib import Path


class EnergyPolicy:
    def __init__(self):
        self.last_time = None
        self.low_since = None

    def evaluate(self, sample):
        timestamp = float(sample["time_s"])
        demand = float(sample["demand_ratio"])
        mode = sample["observed_mode"]
        users = sample["active_ues"]
        coverage = sample["neighbor_coverage_confirmed"]
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("time_s must be finite and nonnegative.")
        if not math.isfinite(demand) or not 0 <= demand <= 1:
            raise ValueError("demand_ratio must be within [0, 1].")
        if mode not in ("active", "energy_saving"):
            raise ValueError("Invalid observed_mode.")
        if type(users) is not int or users < 0:
            raise ValueError("active_ues must be a nonnegative integer.")
        if type(coverage) is not bool:
            raise ValueError("Coverage confirmation must be boolean.")
        if self.last_time is not None:
            if timestamp <= self.last_time:
                raise ValueError("Sample times must strictly increase.")
            if timestamp - self.last_time > 15:
                self.low_since = None
        self.last_time = timestamp
        return self.decide(timestamp, demand, mode, users, coverage)

    def decide(self, timestamp, demand, mode, users, coverage):
        result = {
            "time_s": timestamp,
            "observed_mode": mode,
            "executed": False,
        }
        if mode == "energy_saving":
            self.low_since = None
            if demand >= 0.6 or users > 0 or not coverage:
                result.update(
                    status="recommendation",
                    action="restore_active_mode",
                )
            else:
                result["status"] = "hold_energy_saving"
            return result

        eligible = demand <= 0.2 and users == 0 and coverage
        if not eligible:
            self.low_since = None
            result["status"] = "hold_active"
        else:
            if self.low_since is None:
                self.low_since = timestamp
            duration = timestamp - self.low_since
            result["low_demand_duration_s"] = duration
            if duration >= 30:
                result.update(
                    status="recommendation",
                    action="consider_energy_saving",
                )
            else:
                result["status"] = "pending"
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON array of observations")
    args = parser.parse_args()
    samples = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(samples, list) or not samples:
        parser.error("Input must be a nonempty JSON array.")
    policy = EnergyPolicy()
    for sample in samples:
        print(json.dumps(policy.evaluate(sample)), flush=True)


if __name__ == "__main__":
    main()
