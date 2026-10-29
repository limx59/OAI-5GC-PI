#!/usr/bin/env python3
"""Collect OAI KPM load response without modifying existing xApps."""

import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, os.environ.get(
    "FLEXRIC_SDK_PATH", "/usr/local/lib/python3/dist-packages/xapp_sdk",
))
import xapp_sdk as ric

METRICS = {
    "DRB.UEThpDl": "kbps", "DRB.UEThpUl": "kbps",
    "RRU.PrbTotDl": "percent", "RRU.PrbTotUl": "percent",
}
FIELDS = [
    "received_at_utc", "report_sequence", "node_id", "mcc", "mnc",
    "ran_type", "indication_format", "ue_report_index", "row_index",
    "incomplete", "measurement", "value_type", "value", "unit",
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Collector(ric.kpm_cb):
    def __init__(self, output):
        super().__init__()
        self.output = output
        self.lock = threading.Lock()
        self.closed = False
        self.reports = 0
        self.errors = []

    def handle(self, indication):
        with self.lock:
            if self.closed:
                return
            try:
                self.record(indication)
            except Exception as error:
                self.errors.append(str(error))
                print(f"LOAD_CALLBACK_ERROR: {error}", flush=True)

    def record(self, indication):
        identity = indication.id
        require(identity.nb_id.nb_id == 3584, "Unexpected node ID")
        require((identity.plmn.mcc, identity.plmn.mnc) == (1, 1),
                "Unexpected PLMN")
        require(indication.msg.type == ric.FORMAT_3_INDICATION_MESSAGE,
                "Expected Format 3")
        reports = list(indication.msg.frm_3.meas_report_per_ue)
        require(len(reports) == 1, "Expected one UE report")
        report = reports[0].ind_msg_format_1
        data = list(report.meas_data_lst)
        require(len(data) == 1, "Expected one measurement row")
        row = data[0]
        require(row.incomplete_flag != ric.TRUE_ENUM_VALUE,
                "Incomplete measurement")
        require(row.meas_record_len == report.meas_info_lst_len == 4,
                "Unexpected measurement count")
        received = datetime.now(timezone.utc).isoformat()
        records = []
        names = []
        for value, info in zip(row.meas_record_lst, report.meas_info_lst):
            require(info.meas_type.type == ric.NAME_MEAS_TYPE,
                    "Expected measurement name")
            name = info.meas_type.name
            require(name in METRICS, "Unexpected metric")
            names.append(name)
            if value.value == ric.INTEGER_MEAS_VALUE:
                kind, number = "integer", int(value.int_val)
            elif value.value == ric.REAL_MEAS_VALUE:
                kind, number = "real", float(value.real_val)
            else:
                raise RuntimeError("Missing numeric measurement")
            require(math.isfinite(number) and number >= 0, "Invalid value")
            records.append([
                received, self.reports + 1, 3584, 1, 1,
                int(identity.type), 3, 0, 0, 0,
                name, kind, number, METRICS[name],
            ])
        require(len(set(names)) == 4, "Repeated metric")
        with self.output.open("a", newline="") as stream:
            csv.writer(stream).writerows(records)
        self.reports += 1
        print(f"LOAD_REPORT={self.reports}", flush=True)


def main():
    output = Path(os.environ.get("XAPP_OUTPUT", "/evidence/kpm.csv"))
    result_path = Path(os.environ.get("PROBE_OUTPUT", "/evidence/probe.json"))
    duration = float(os.environ.get("KPM_RECORD_SECONDS", "110"))
    require(5 <= duration <= 300, "Invalid recording duration")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="") as stream:
        csv.writer(stream).writerow(FIELDS)
    callback = Collector(output)
    result = {"passed": False, "cleanup_errors": []}
    handle = None
    initialized = False
    try:
        ric.init(sys.argv)
        initialized = True
        time.sleep(2)
        nodes = [n for n in ric.conn_e2_nodes()
                 if n.id.nb_id.nb_id == 3584]
        require(len(nodes) == 1, "Expected one OAI node 3584")
        handle = ric.report_kpm_sm(
            nodes[0].id, ric.Interval_ms_1000, list(METRICS), callback,
        )
        require(handle >= 0, "Subscription rejected")
        print("LOAD_SUBSCRIPTION_READY", flush=True)
        time.sleep(duration)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if handle is not None and handle >= 0:
            try:
                ric.rm_report_kpm_sm(handle)
                time.sleep(6)
            except Exception as error:
                result["cleanup_errors"].append(str(error))
        if initialized:
            deadline = time.monotonic() + 15
            while ric.try_stop == 0 and time.monotonic() < deadline:
                time.sleep(0.2)
            if ric.try_stop == 0:
                result["cleanup_errors"].append("SDK shutdown timeout")
        with callback.lock:
            callback.closed = True
            result["reports"] = callback.reports
            result["callback_errors"] = list(callback.errors)
        result["association_basis"] = "Receipt timestamps"
        result["passed"] = (
            "error" not in result and not result["cleanup_errors"]
            and not result["callback_errors"] and result["reports"] >= 80
        )
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
