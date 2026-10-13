#!/usr/bin/env python3
"""Recommend traffic steering from normalized cell loads; no E2 control."""

import argparse
import json
import math
from pathlib import Path


class SteeringPolicy:
    def __init__(self):
        self.last_time = None
        self.last_recommendation = None
        self.candidate = None
        self.consecutive = 0

    def evaluate(self, sample):
        timestamp = float(sample["time_s"])
        cells = sample["cells"]
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("time_s must be finite and nonnegative.")
        if self.last_time is not None and timestamp <= self.last_time:
            raise ValueError("Sample times must strictly increase.")
        if not isinstance(cells, dict) or len(cells) < 2:
            raise ValueError("Each sample requires at least two cells.")
        loads = {}
        for cell, load in cells.items():
            if not isinstance(cell, str) or not cell:
                raise ValueError("Cell IDs must be nonempty strings.")
            value = float(load)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Cell loads must be normalized to [0, 1].")
            loads[cell] = value
        self.last_time = timestamp
        return self.decide(timestamp, loads)

    def decide(self, timestamp, loads):
        source = max(loads, key=loads.get)
        target = min(loads, key=loads.get)
        eligible = (
            source != target
            and loads[source] >= 0.8
            and loads[target] <= 0.6
            and loads[source] - loads[target] >= 0.2
        )
        pair = (source, target) if eligible else None
        if pair is None:
            self.candidate = None
            self.consecutive = 0
            return {"time_s": timestamp, "status": "balanced"}
        if pair == self.candidate:
            self.consecutive += 1
        else:
            self.candidate = pair
            self.consecutive = 1

        result = {
            "time_s": timestamp,
            "source": source,
            "target": target,
            "source_load": loads[source],
            "target_load": loads[target],
        }
        if self.consecutive < 2:
            result["status"] = "pending"
        elif (
            self.last_recommendation is not None
            and timestamp - self.last_recommendation < 30
        ):
            result["status"] = "cooldown"
        else:
            self.last_recommendation = timestamp
            result["status"] = "recommendation"
            result["action"] = "consider_ue_migration"
            result["executed"] = False
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON array of load samples")
    args = parser.parse_args()
    samples = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(samples, list) or not samples:
        parser.error("Input must be a nonempty JSON array.")
    policy = SteeringPolicy()
    for sample in samples:
        print(json.dumps(policy.evaluate(sample)), flush=True)


if __name__ == "__main__":
    main()
