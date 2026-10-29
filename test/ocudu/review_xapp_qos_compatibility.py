"""Review original shared QoS xApp normal-flow compatibility."""

import ast
import math
import re


METRICS = {"DRB.UEThpDl", "DRB.UEThpUl"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(stdout, stderr, direction, case):
    require(direction in ("uplink", "downlink"), "Invalid direction")
    require(case in ("alerts", "no-alerts"), "Invalid threshold case")
    threshold = 1e9 if case == "alerts" else 0.0
    combined = stdout + "\n" + stderr
    for marker in (
        "callback error", "Traceback", "Assertion", "Skipping mismatched",
        "Unsupported", "No subscriptions:", "UNKNOWN:", "RECOVERY:",
        "KPM_DELETE_REJECTED",
    ):
        require(marker.lower() not in combined.lower(),
                f"QoS failure marker: {marker}")

    subscriptions = re.findall(
        r"^Subscribed: node=(\d+), metrics=(.+)$", stdout, re.M)
    require(len(subscriptions) == 1, "Expected one QoS subscription")
    node, raw = subscriptions[0]
    actions = ast.literal_eval(raw)
    require(node == "420" and isinstance(actions, list)
            and len(actions) == 2 and set(actions) == METRICS,
            "Wrong QoS subscription")
    headers = re.findall(
        r"^QoS threshold=(\S+) in agent-reported units; "
        r"required consecutive reports=(\d+)\.$", stdout, re.M)
    require(len(headers) == 1
            and float(headers[0][0]) == threshold
            and int(headers[0][1]) == 2, "Wrong QoS threshold configuration")
    require(stdout.count("SUBSCRIPTION DELETE RESPONSE rx") == 1,
            "Expected one normal deletion response")

    values = {name: [] for name in METRICS}
    alerts = {name: 0 for name in METRICS}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("QoS:"):
            match = re.fullmatch(
                r"QoS: node=(\d+) metric=(\S+) mean=(\S+) samples=(\d+)", line)
            require(match is not None, "Malformed QoS observation")
            node, name, raw, count = match.groups()
            require(node == "420" and name in METRICS, "Wrong observation")
            value = float(raw)
            require(math.isfinite(value) and value >= 0 and int(count) == 1,
                    "Invalid single-UE QoS value")
            require(case != "alerts" or value < threshold,
                    "Forced-alert threshold is too low")
            values[name].append(value)
        elif line.startswith("ALERT:"):
            match = re.fullmatch(
                r"ALERT: node=(\d+) metric=(\S+) below (\S+) for "
                r"(\d+) consecutive reports\.", line)
            require(match is not None, "Malformed alert")
            node, name, limit, consecutive = match.groups()
            require(case == "alerts" and node == "420" and name in METRICS,
                    "Unexpected alert")
            require(float(limit) == threshold and int(consecutive) == 2
                    and len(values[name]) == 2 and alerts[name] == 0,
                    "Alert timing/count mismatch")
            alerts[name] += 1

    require(all(len(items) >= 5 for items in values.values()),
            "Insufficient QoS observations")
    require(all(count == (1 if case == "alerts" else 0)
                for count in alerts.values()), "Missing or repeated alerts")
    active = "DRB.UEThpUl" if direction == "uplink" else "DRB.UEThpDl"
    positive = sum(value > 0 for value in values[active][1:])
    require(positive >= 2, "Insufficient later active-direction positive values")
    return {
        "passed": True, "direction": direction, "case": case,
        "threshold_raw_kbps": threshold, "consecutive_reports": 2,
        "observations": {name: len(items) for name, items in values.items()},
        "alerts": alerts, "active_metric": active,
        "later_positive_observations": positive,
        "scope": "Original shared QoS xApp; forced-threshold logic",
        "load_fault_or_recovery_validated": False,
    }
