"""Common throughput representation; no capacity normalization."""

from datetime import datetime
import math

METRICS = {"DRB.UEThpDl": "downlink", "DRB.UEThpUl": "uplink"}
SOURCES = {
    "oai": {
        "node_id": "3584",
        "source_basis": "RLC PDU byte delta / configured granularity",
        "time_basis": "receipt_time",
    },
    "ocudu": {
        "node_id": "420",
        "source_basis": "RLC provider mean throughput",
        "time_basis": "nominal_kpm_window",
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def timestamp(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "Timestamp must include timezone")
    return result


def convert(row, system):
    require(system in SOURCES, "Unknown system")
    source = SOURCES[system]
    name = row["measurement"]
    require(name in METRICS, "Only throughput has a common mapping")
    require(row["node_id"] == source["node_id"], "Unexpected node")
    require((row["mcc"], row["mnc"]) == ("1", "1"), "Unexpected PLMN")
    require(row["unit"] == "kbps", "Expected raw kbps")
    require(row["incomplete"] == "0", "Incomplete measurement")
    require(row["value_type"] in ("integer", "real"), "Missing numeric value")
    value = float(row["value"])
    require(math.isfinite(value) and value >= 0, "Invalid throughput")
    received = timestamp(row["received_at_utc"])
    result = {
        "system": system, "node_id": row["node_id"],
        "direction": METRICS[name],
        "received_at_utc": received.isoformat(),
        "measurement": name, "value_bit_s": value * 1000,
        "source_basis": source["source_basis"],
        "time_basis": source["time_basis"],
        "normalized_cell_load": None,
        "eligible_for_normalized_load_policy": False,
    }
    if system == "ocudu":
        require(row["window_basis"] == "header_plus_row_granularity_nominal",
                "Unexpected nominal-window basis")
        start = timestamp(row["nominal_window_start_utc"])
        end = timestamp(row["nominal_window_end_utc"])
        require(end > start, "Invalid nominal window")
        require(math.isclose(float(row["value_bits_per_second"]),
                             value * 1000, rel_tol=1e-9, abs_tol=1e-6),
                "Throughput conversion mismatch")
        result["nominal_window_start_utc"] = start.isoformat()
        result["nominal_window_end_utc"] = end.isoformat()
    return result
