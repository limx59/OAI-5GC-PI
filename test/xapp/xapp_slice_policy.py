#!/usr/bin/env python3
"""Recommend slice PRB budget percentages from supplied demand estimates."""

import argparse
import json
import math
from pathlib import Path


def validate(slices):
    if not isinstance(slices, list) or not slices:
        raise ValueError("Input must contain a nonempty slice list.")
    names = set()
    result = []
    for item in slices:
        name = item["slice_id"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("Slice IDs must be unique nonempty strings.")
        names.add(name)
        minimum = float(item["min_prb_percent"])
        demand = float(item["demand_prb_percent"])
        priority = float(item["priority"])
        if not all(math.isfinite(v) for v in (minimum, demand, priority)):
            raise ValueError("Slice parameters must be finite.")
        if not 0 <= minimum <= 100 or not 0 <= demand <= 100:
            raise ValueError("PRB percentages must be within [0, 100].")
        if priority <= 0:
            raise ValueError("Slice priority must be positive.")
        result.append({
            "slice_id": name, "minimum": minimum,
            "demand": demand, "priority": priority,
        })
    if sum(item["minimum"] for item in result) > 100:
        raise ValueError("Minimum slice budgets exceed 100 percent.")
    return result


def allocate(slices):
    items = validate(slices)
    budgets = [item["minimum"] for item in items]
    remaining = 100.0 - sum(budgets)
    while remaining > 1e-9:
        deficits = [
            max(item["demand"] - budget, 0.0)
            for item, budget in zip(items, budgets)
        ]
        active = [i for i, deficit in enumerate(deficits) if deficit > 1e-9]
        if not active:
            break
        scale = max(items[i]["priority"] for i in active)
        weights = {
            i: deficits[i] * (items[i]["priority"] / scale)
            for i in active
        }
        total_weight = sum(weights.values())
        increments = {
            i: min(deficits[i], remaining * weights[i] / total_weight)
            for i in active
        }
        used = sum(increments.values())
        if used <= 1e-9:
            break
        for i, increment in increments.items():
            budgets[i] += increment
        remaining = max(100.0 - sum(budgets), 0.0)

    return {
        "executed": False,
        "unused_prb_percent": remaining,
        "slices": [
            {
                "slice_id": item["slice_id"],
                "recommended_prb_percent": budget,
                "unmet_demand_percent": max(item["demand"] - budget, 0.0),
            }
            for item, budget in zip(items, budgets)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON array of slice demands")
    args = parser.parse_args()
    slices = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(allocate(slices), indent=2))


if __name__ == "__main__":
    main()
