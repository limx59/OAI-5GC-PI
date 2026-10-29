"""Review bounded single-link load response; no steering control."""

from datetime import datetime, timedelta
import math
from statistics import median


METRICS = {
    "RRU.PrbAvailDl": "PRB", "RRU.PrbAvailUl": "PRB",
    "RRU.PrbUsedDl": "PRB", "RRU.PrbUsedUl": "PRB",
    "RRU.PrbTotDl": "percent", "RRU.PrbTotUl": "percent",
    "DRB.RlcSduTransmittedVolumeDL": "kbit",
    "DRB.RlcSduTransmittedVolumeUL": "kbit",
    "DRB.UEThpDl": "kbps", "DRB.UEThpUl": "kbps",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def timestamp(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "Timestamp must include timezone")
    return result


def review(rows, probe, phases):
    require(bool(rows), "Empty statistics CSV")
    require(probe["passed"] and not probe["callback_errors"]
            and not probe["cleanup_errors"], "Collector did not pass")
    expected = {
        f"{direction}-{phase}"
        for direction in ("uplink", "downlink")
        for phase in ("low-before", "high", "low-after")
    }
    require(set(phases) == expected, "Expected six load phases")
    groups = {}
    identities = set()
    for row in rows:
        require(None not in row and None not in row.values(),
                "Malformed CSV row")
        require((row["node_id"], row["mcc"], row["mnc"]) == ("420", "1", "1"),
                "Unexpected node identity")
        require(row["ue_report_index"] == "0" and row["row_index"] == "0",
                "Expected one UE and one measurement row")
        require(row["incomplete"] == "0", "Incomplete measurement")
        identities.add((row["cu_du_id"], row["ue_id_type"],
                        row["gnb_cu_ue_f1ap"]))
        name = row["measurement"]
        require(name in METRICS and row["unit"] == METRICS[name],
                "Unexpected metric or unit")
        require(row["window_basis"] == "header_plus_row_granularity_nominal",
                "Unexpected window basis")
        require(int(row["granularity_ms"]) == 1000,
                "Expected one-second granularity")
        start = timestamp(row["nominal_window_start_utc"])
        end = timestamp(row["nominal_window_end_utc"])
        require(abs((end - start).total_seconds() - 1) < 0.001,
                "Invalid nominal window")
        require(row["value_type"] in ("integer", "real"),
                "Expected numeric statistics")
        value = float(row["value"])
        require(math.isfinite(value) and value >= 0, "Invalid numeric value")
        if name.startswith("RRU.PrbTot"):
            require(value <= 100, "PRB utilization exceeds 100 percent")
        if name.startswith("DRB.UEThp"):
            require(math.isclose(float(row["value_bits_per_second"]),
                                 value * 1000, rel_tol=1e-9, abs_tol=1e-6),
                    "Throughput conversion mismatch")
        key = row["report_sequence"]
        group = groups.setdefault(key, {})
        require(name not in group, "Repeated metric")
        group[name] = row
    require(len(identities) == 1, "UE/component identity changed")
    require(len(groups) >= 80, "Insufficient recording duration")
    for group in groups.values():
        require(set(group) == set(METRICS), "Missing measurements")
        require(len({r["received_at_utc"] for r in group.values()}) == 1,
                "Inconsistent report receipt time")
        require(len({r["nominal_window_start_utc"]
                     for r in group.values()}) == 1,
                "Inconsistent report window")

    results = {}
    previous_end = None
    for direction in ("uplink", "downlink"):
        suffix = "Ul" if direction == "uplink" else "Dl"
        for phase, offered in (
            ("low-before", 200000), ("high", 1000000), ("low-after", 200000),
        ):
            key = f"{direction}-{phase}"
            item = phases[key]
            require(item["direction"] == direction and item["phase"] == phase,
                    "Phase label mismatch")
            require(item["offered_bit_s"] == offered, "Unexpected offered load")
            start = timestamp(item["started_utc"])
            end = timestamp(item["finished_utc"])
            require(end > start, "Invalid traffic interval")
            require(previous_end is None or start >= previous_end,
                    "Traffic phases overlap or are out of order")
            previous_end = end
            receiver = item["receiver"]
            rate = float(receiver["bits_per_second"])
            require(math.isfinite(rate) and 0.8 * offered <= rate <= 1.2 * offered
                    and receiver["bytes"] > 0
                    and 0 <= receiver["lost_percent"] <= 5,
                    "Traffic receiver acceptance failed")
            interior = [
                group for group in groups.values()
                if timestamp(group["DRB.UEThp" + suffix]
                             ["nominal_window_start_utc"])
                >= start + timedelta(seconds=2)
                and timestamp(group["DRB.UEThp" + suffix]
                              ["nominal_window_end_utc"])
                <= end - timedelta(seconds=1)
            ]
            require(len(interior) >= 5, f"{key}: insufficient interior reports")
            throughput = median(
                float(group["DRB.UEThp" + suffix]["value"]) * 1000
                for group in interior
            )
            ratio = throughput / rate
            require(0.7 <= ratio <= 1.5, f"{key}: KPM/iperf ratio failed")
            results[key] = {
                "samples": len(interior),
                "median_kpm_bit_s": throughput,
                "kpm_to_iperf_ratio": ratio,
                "median_prb_utilization_percent": median(
                    float(group["RRU.PrbTot" + suffix]["value"])
                    for group in interior
                ),
            }
        before = results[f"{direction}-low-before"]["median_kpm_bit_s"]
        high = results[f"{direction}-high"]["median_kpm_bit_s"]
        after = results[f"{direction}-low-after"]["median_kpm_bit_s"]
        require(before > 0 and after > 0
                and high / before >= 3 and high / after >= 3,
                f"{direction}: low/high contrast failed")
        require(0.7 <= after / before <= 1.3,
                f"{direction}: return-to-low response failed")

    return {
        "passed": True, "rows": len(rows), "reports": len(groups),
        "phases": results,
        "association_basis": "Interior nominal KPM windows versus receiver rate",
        "scheduler_capacity_validated": False,
        "migration_recommended": False,
        "control_executed": False,
    }
