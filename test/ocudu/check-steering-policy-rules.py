#!/usr/bin/env python3
"""Check unchanged policy rules with controlled normalized-load fixtures."""

import hashlib
import json
from pathlib import Path
import runpy


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check(policy_class):
    policy = policy_class()
    results = []
    scenarios = [
        (0, 0.9, 0.2, "pending", "cell-a", "cell-b"),
        (1, 0.9, 0.2, "recommendation", "cell-a", "cell-b"),
        (2, 0.9, 0.2, "cooldown", "cell-a", "cell-b"),
        (3, 0.5, 0.5, "balanced", None, None),
        (4, 0.2, 0.9, "pending", "cell-b", "cell-a"),
        (5, 0.2, 0.9, "cooldown", "cell-b", "cell-a"),
        (30.999, 0.2, 0.9, "cooldown", "cell-b", "cell-a"),
        (31, 0.2, 0.9, "recommendation", "cell-b", "cell-a"),
        (32, 0.9, 0.2, "pending", "cell-a", "cell-b"),
        (33, 0.9, 0.2, "cooldown", "cell-a", "cell-b"),
        (61, 0.9, 0.2, "recommendation", "cell-a", "cell-b"),
    ]
    for timestamp, a, b, status, source, target in scenarios:
        result = policy.evaluate({
            "time_s": timestamp, "cells": {"cell-a": a, "cell-b": b},
        })
        require(result["status"] == status, f"Unexpected status at {timestamp}")
        if source is not None:
            require((result["source"], result["target"]) == (source, target),
                    "Recommendation direction mismatch")
        if status == "recommendation":
            require(result["executed"] is False
                    and result["action"] == "consider_ue_migration",
                    "Expected advisory-only result")
        results.append(result)

    for a, b, eligible in (
        (0.8, 0.59, True),
        (0.79, 0.2, False),
        (0.9, 0.61, False),
        (0.8, 0.6, True),
    ):
        instance = policy_class()
        first = instance.evaluate({"time_s": 0, "cells": {"a": a, "b": b}})
        second = instance.evaluate({"time_s": 1, "cells": {"a": a, "b": b}})
        require(first["status"] == ("pending" if eligible else "balanced"),
                "Eligibility boundary mismatch")
        require(second["status"] == (
            "recommendation" if eligible else "balanced"),
            "Consecutive-report boundary mismatch")

    invalid = [
        {"time_s": -1, "cells": {"a": 0.9, "b": 0.2}},
        {"time_s": float("nan"), "cells": {"a": 0.9, "b": 0.2}},
        {"time_s": 0, "cells": {"a": 0.9}},
        {"time_s": 0, "cells": {"a": 1.1, "b": 0.2}},
        {"time_s": 0, "cells": {"a": -0.1, "b": 0.2}},
        {"time_s": 0, "cells": {"a": float("nan"), "b": 0.2}},
        {"time_s": 0, "cells": {"": 0.9, "b": 0.2}},
    ]
    for sample in invalid:
        try:
            policy_class().evaluate(sample)
        except ValueError:
            continue
        raise RuntimeError("Invalid policy input accepted")

    for timestamp in (0, -1):
        instance = policy_class()
        instance.evaluate({"time_s": 0, "cells": {"a": 0.5, "b": 0.5}})
        try:
            instance.evaluate({
                "time_s": timestamp, "cells": {"a": 0.9, "b": 0.2},
            })
        except ValueError:
            continue
        raise RuntimeError("Non-increasing time accepted")
    return {
        "passed": True, "timeline": results,
        "scope": "Controlled normalized-load policy fixtures",
        "live_dual_node_validated": False,
        "cross_vendor_prb_mapping_validated": False,
        "control_executed": False,
    }


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "test/xapp/xapp_traffic_steering.py"
    policy_class = runpy.run_path(str(source))["SteeringPolicy"]
    result = check(policy_class)
    result["policy_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
