"""Review OAI load response using receipt-time interior samples."""

from datetime import datetime, timedelta
import math
from statistics import median

METRICS = {
    "DRB.UEThpDl": "kbps", "DRB.UEThpUl": "kbps",
    "RRU.PrbTotDl": "percent", "RRU.PrbTotUl": "percent",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def stamp(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "Timestamp lacks timezone")
    return result


def review(rows, probe, phases):
    require(probe["passed"] and not probe["callback_errors"]
            and not probe["cleanup_errors"], "Collector failed")
    require(bool(rows), "Empty CSV")
    groups = {}
    roles = set()
    for row in rows:
        require(None not in row and None not in row.values(), "Malformed CSV")
        require((row["node_id"], row["mcc"], row["mnc"],
                 row["indication_format"], row["ue_report_index"],
                 row["row_index"], row["incomplete"])
                == ("3584", "1", "1", "3", "0", "0", "0"),
                "Unexpected identity or report format")
        roles.add(row["ran_type"])
        name = row["measurement"]
        require(name in METRICS and row["unit"] == METRICS[name],
                "Unexpected metric or unit")
        require(row["value_type"] in ("real", "integer"), "Missing value")
        value = float(row["value"])
        require(math.isfinite(value) and value >= 0, "Invalid value")
        stamp(row["received_at_utc"])
        group = groups.setdefault(row["report_sequence"], {})
        require(name not in group, "Repeated metric")
        group[name] = row
    require(len(roles) == 1, "Node role changed")
    require(len(groups) >= 80, "Insufficient recording duration")
    require(probe["reports"] == len(groups), "Probe/CSV report mismatch")
    for group in groups.values():
        require(set(group) == set(METRICS), "Missing metric")
        require(len({r["received_at_utc"] for r in group.values()}) == 1,
                "Report timestamp mismatch")
    expected = {
        f"{direction}-{phase}"
        for direction in ("uplink", "downlink")
        for phase in ("low-before", "high", "low-after")
    }
    require(set(phases) == expected, "Expected six phases")
    results = {}
    previous_end = None
    for direction in ("uplink", "downlink"):
        suffix = "Ul" if direction == "uplink" else "Dl"
        for phase, offered in (
            ("low-before", 200000), ("high", 1000000), ("low-after", 200000),
        ):
            key = f"{direction}-{phase}"
            item = phases[key]
            require((item["direction"], item["phase"], item["offered_bit_s"])
                    == (direction, phase, offered), "Phase metadata mismatch")
            start, end = stamp(item["started_utc"]), stamp(item["finished_utc"])
            require(end > start and (previous_end is None or start >= previous_end),
                    "Invalid phase ordering")
            previous_end = end
            receiver = item["receiver"]
            rate = float(receiver["bits_per_second"])
            require(math.isfinite(rate) and 0.8 * offered <= rate <= 1.2 * offered
                    and receiver["bytes"] > 0
                    and 0 <= receiver["lost_percent"] <= 5,
                    "Traffic receiver acceptance failed")
            selected = [
                g for g in groups.values()
                if start + timedelta(seconds=3)
                <= stamp(g["DRB.UEThp" + suffix]["received_at_utc"])
                <= end - timedelta(seconds=1)
            ]
            require(len(selected) >= 5, f"{key}: insufficient interior samples")
            throughput = median(
                float(g["DRB.UEThp" + suffix]["value"]) * 1000
                for g in selected
            )
            ratio = throughput / rate
            require(0.7 <= ratio <= 1.5, f"{key}: KPM/iperf mismatch")
            results[key] = {
                "samples": len(selected),
                "median_kpm_bit_s": throughput,
                "kpm_to_iperf_ratio": ratio,
                "median_prb_raw_percent": median(
                    float(g["RRU.PrbTot" + suffix]["value"]) for g in selected
                ),
            }
        before = results[f"{direction}-low-before"]["median_kpm_bit_s"]
        high = results[f"{direction}-high"]["median_kpm_bit_s"]
        after = results[f"{direction}-low-after"]["median_kpm_bit_s"]
        require(before > 0 and after > 0
                and high / before >= 3 and high / after >= 3,
                f"{direction}: low/high contrast failed")
        require(0.7 <= after / before <= 1.3, "Return-to-low response failed")
    return {
        "passed": True, "rows": len(rows), "reports": len(groups),
        "phases": results, "association_basis": "Receipt-time interior",
        "prb_cross_vendor_equivalence_validated": False,
        "control_executed": False,
    }
