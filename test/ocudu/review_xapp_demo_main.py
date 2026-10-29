"""Review the unchanged shared KPM demo's bounded normal-flow output."""

import ast
import math
import re


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(stdout, stderr, metrics, ue_level=True):
    combined = stdout + "\n" + stderr
    for marker in (
        "callback error", "Traceback", "Assertion", "Unsupported format",
        "Measurement names and values do not align",
        "Warning: incomplete", "No subscriptions:", "KPM_DELETE_REJECTED",
    ):
        require(marker.lower() not in combined.lower(),
                f"Demo failure marker: {marker}")

    subscriptions = re.findall(
        r"^Subscribed: node=(\d+), metrics=(.+)$", stdout, re.M)
    require(len(subscriptions) == 1, "Expected one demo subscription")
    node, actions = subscriptions[0]
    requested = ast.literal_eval(actions)
    require(node == "420" and isinstance(requested, list)
            and len(requested) == len(metrics)
            and set(requested) == set(metrics), "Wrong subscription target")
    require(stdout.count("SUBSCRIPTION DELETE RESPONSE rx") == 1,
            "Expected one deletion response")

    reports, current = [], None
    ue_markers = 0
    for line in stdout.splitlines():
        match = re.fullmatch(r"KPM node=(\d+)", line.strip())
        if match:
            require(match.group(1) == "420", "Wrong report node")
            current = {}
            reports.append(current)
            continue
        match = re.fullmatch(r"UE report index=(\d+)", line.strip())
        if match:
            require(current is not None and match.group(1) == "0",
                    "Unexpected UE report index")
            ue_markers += 1
            continue
        match = re.fullmatch(r"(\S+) = (.+)", line.strip())
        if not match:
            continue
        name, raw = match.groups()
        require(current is not None and name in metrics and name not in current,
                "Unexpected or repeated measurement")
        if raw == "no value":
            current[name] = None
        else:
            value = float(raw)
            require(math.isfinite(value) and value >= 0,
                    "Invalid numeric measurement")
            if name == "DRB.PacketSuccessRateUlgNBUu":
                require(value <= 100, "Success percentage exceeds 100")
            current[name] = value

    require(len(reports) >= 5, "Insufficient demo reports")
    require(all(set(item) == set(metrics) for item in reports),
            "Missing measurement in demo report")
    require(ue_markers == (len(reports) if ue_level else 0),
            "Unexpected UE-report structure")
    numeric = {
        name: sum(item[name] is not None for item in reports)
        for name in metrics
    }
    require(all(count >= 3 for count in numeric.values()),
            "Insufficient numeric measurements")
    return {
        "passed": True, "reports": len(reports),
        "numeric_samples": numeric, "ue_report_markers": ue_markers,
        "shared_subscription_demo_exercised": True,
        "traffic_comparison_performed": False,
        "scope": "Single-node normal subscription/report/delete flow",
    }
