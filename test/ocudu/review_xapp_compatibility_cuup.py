"""Review CU-UP shared-recorder CSV without treating success as loss."""

from datetime import datetime, timedelta
import math
from statistics import median


METRIC = "DRB.PacketSuccessRateUlgNBUu"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(rows, probe, directions):
    require(bool(rows), "Empty CU-UP CSV")
    require(probe["passed"] and not probe["callback_errors"]
            and not probe["cleanup_errors"], "Probe did not pass")
    require(probe["role"] == "ngran_gNB_CUUP", "Wrong probe role")
    reports, numeric, missing = set(), [], 0
    ran_types = set()
    for row in rows:
        require(None not in row and None not in row.values(),
                "Malformed CSV row")
        require((int(row["node_id"]), int(row["mcc"]),
                 int(row["mnc"]), int(row["indication_format"]))
                == (420, 1, 1, 1), "Wrong identity or format")
        require(row["measurement"] == METRIC, "Wrong CU-UP metric")
        require(row["ue_report_index"] == "" and row["row_index"] == "0",
                "Expected one node-level measurement row")
        require(row["incomplete"] in ("0", "1"), "Invalid incomplete flag")
        stamp = datetime.fromisoformat(row["received_at_utc"])
        require(stamp.utcoffset() == timedelta(0), "Expected UTC receipt time")
        require(stamp not in reports, "Repeated exported report timestamp")
        reports.add(stamp)
        ran_types.add(row["ran_type"])
        if row["value_type"] == "no_value":
            require(row["value"] == "", "Missing value must remain empty")
            missing += 1
        else:
            require(row["value_type"] in ("integer", "real"),
                    "Unknown value type")
            value = float(row["value"])
            require(math.isfinite(value) and 0 <= value <= 100,
                    "Invalid PDCP success percentage")
            if row["incomplete"] == "0":
                numeric.append((stamp, value))

    require(len(reports) >= 30, "Insufficient CU-UP reports")
    require(len(ran_types) == 1, "Node type changed")
    require(probe["reports"] == len(reports), "Probe/CSV count mismatch")
    require(probe["complete_numeric_samples"] == {METRIC: len(numeric)},
            "Probe/CSV numeric count mismatch")
    item = directions["uplink"]
    start = datetime.fromisoformat(item["started_utc"]) + timedelta(seconds=2)
    end = datetime.fromisoformat(item["finished_utc"]) - timedelta(seconds=1)
    samples = [value for stamp, value in numeric if start <= stamp <= end]
    require(len(samples) >= 5, "Insufficient interior UL success reports")
    success = median(samples)
    require(success >= 95, "UL median success below 95 percent")
    return {
        "rows": len(rows), "reports": len(reports),
        "complete_numeric_rows": len(numeric), "no_value_rows": missing,
        "metric": METRIC, "unit": "percent",
        "ul_interior_reports": len(samples),
        "ul_median_success_percent": success,
        "association_basis": "Receipt time; cached PDCP history",
        "application_loss_comparison_performed": False,
        "source_provenance_validated": False,
        "component_identity_exported": False,
    }
