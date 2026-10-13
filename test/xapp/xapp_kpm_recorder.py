#!/usr/bin/env python3
"""Record KPM measurements as CSV using the existing subscription demo."""

import csv
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import xapp_kpm as demo

OUTPUT = Path(os.environ.get(
    "XAPP_OUTPUT", "/tmp/oai-pi-xapp-kpm.csv"
)).expanduser()
WRITE_LOCK = threading.Lock()

FIELDS = [
    "received_at_utc", "node_id", "mcc", "mnc", "ran_type",
    "indication_format", "ue_report_index", "row_index",
    "incomplete", "measurement", "value_type", "value",
]


class RecorderCallback(demo.KPMCallback):
    def __init__(self):
        super().__init__()
        self.report_count = 0

    def handle(self, indication):
        try:
            self.record(indication)
        except Exception as error:
            print(f"CSV callback error: {error}",
                  file=demo.sys.stderr, flush=True)

    def record(self, indication):
        ric = demo.ric
        message = indication.msg
        if message.type == ric.FORMAT_1_INDICATION_MESSAGE:
            reports = [("", message.frm_1)]
            report_format = 1
        elif message.type == ric.FORMAT_3_INDICATION_MESSAGE:
            # Keep parent SWIG objects alive while reading nested reports.
            ue_reports = list(message.frm_3.meas_report_per_ue)
            reports = [
                (index, ue.ind_msg_format_1)
                for index, ue in enumerate(ue_reports)
            ]
            report_format = 3
        else:
            print(f"Unsupported KPM format: {message.type}", flush=True)
            return

        received = datetime.now(timezone.utc).isoformat()
        identity = indication.id
        records = []
        for ue_index, report in reports:
            for row_index, row in enumerate(report.meas_data_lst):
                if row.meas_record_len != report.meas_info_lst_len:
                    print("Skipping mismatched measurement row.", flush=True)
                    continue
                for value, info in zip(
                    row.meas_record_lst, report.meas_info_lst
                ):
                    name = (
                        info.meas_type.name
                        if info.meas_type.type == ric.NAME_MEAS_TYPE
                        else info.meas_type.id
                    )
                    if value.value == ric.INTEGER_MEAS_VALUE:
                        kind, result = "integer", value.int_val
                    elif value.value == ric.REAL_MEAS_VALUE:
                        kind, result = "real", value.real_val
                    else:
                        kind, result = "no_value", ""
                    records.append([
                        received, identity.nb_id.nb_id,
                        identity.plmn.mcc, identity.plmn.mnc,
                        identity.type, report_format, ue_index, row_index,
                        int(row.incomplete_flag == ric.TRUE_ENUM_VALUE),
                        name, kind, result,
                    ])
        self.write_records(records)

    def write_records(self, records):
        if not records:
            return
        with WRITE_LOCK:
            with OUTPUT.open("a", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerows(records)
            self.report_count += 1
            print(f"Recorded {len(records)} measurements -> {OUTPUT}",
                  flush=True)


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting previous experiment data.
    with OUTPUT.open("x", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(FIELDS)
    print(f"CSV output: {OUTPUT}", flush=True)
    demo.KPMCallback = RecorderCallback
    demo.main()


if __name__ == "__main__":
    main()
