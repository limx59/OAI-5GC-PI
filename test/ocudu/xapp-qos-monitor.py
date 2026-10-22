#!/usr/bin/env python3
"""Record OCUDU DU QoS metrics and emit advisory state events."""

import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, os.environ.get(
    "FLEXRIC_SDK_PATH",
    "/usr/local/lib/python3/dist-packages/xapp_sdk",
))
import xapp_sdk as ric
from qos_monitor_state import MonitorState, RULES, normalize

FIELDS = [
    "received_at_utc", "report_sequence", "node_id", "mcc", "mnc",
    "cu_du_id", "ue_id_type", "gnb_cu_ue_f1ap",
    "ue_report_index", "row_index", "collect_start_ntp64",
    "collect_start_utc", "granularity_ms",
    "nominal_window_start_utc", "nominal_window_end_utc",
    "window_basis", "incomplete", "measurement",
    "value_type", "value", "unit", "value_bits_per_second",
    "normalized_value", "normalized_unit",
]


def ntp_utc(raw):
    raw = int(raw)
    # The SDK binding exposes some uint64_t values as signed int64.
    if -(1 << 63) <= raw < 0:
        raw += 1 << 64
    if not 0 < raw < 2**64:
        raise ValueError(f"Invalid NTP64 timestamp: raw={raw!r}, hex={raw:x}")
    seconds = (raw >> 32) - 2208988800
    micros = ((raw & 0xffffffff) * 1000000) // 2**32
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=seconds, microseconds=micros,
    )


class Recorder(ric.kpm_cb):
    def __init__(self, output):
        ric.kpm_cb.__init__(self)
        self.output = output
        self.lock = threading.Lock()
        self.reports = 0
        self.errors = []
        self.monitor = MonitorState()
        self.events_path = output.with_suffix('.events.jsonl')
        self.events_path.open('x').close()
        self.emit(self.monitor.reconnect())

    def emit(self, event):
        event = {
            "received_at_utc": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
        print("QOS_EVENT " + json.dumps(event), flush=True)

    def check_silence(self):
        with self.lock:
            for event in self.monitor.expire():
                self.emit(event)

    def handle(self, indication):
        with self.lock:
            try:
                self.record(indication)
            except Exception as error:
                self.errors.append(str(error))
                print(f"CSV callback error: {error}", file=sys.stderr, flush=True)

    def record(self, indication):
        if indication.msg.type != ric.FORMAT_3_INDICATION_MESSAGE:
            raise ValueError("Expected UE-level indication Format 3")
        identity = indication.id
        if identity.nb_id.nb_id != 420:
            raise ValueError("Unexpected node identity")

        received = datetime.now(timezone.utc)
        header = indication.hdr.kpm_ric_ind_hdr_format_1
        raw = int(header.collectStartTime)
        if -(1 << 63) <= raw < 0:
            raw += 1 << 64
        collected = ntp_utc(raw)
        delta = (received - collected).total_seconds()
        if abs(delta) > 30:
            raise ValueError(
                f"Header timestamp mismatch: raw={raw}, hex={raw:016x}, "
                f"decoded_utc={collected.isoformat()}, "
                f"received_utc={received.isoformat()}, delta_s={delta:.6f}"
            )

        node_ids = list(identity.cu_du_id)
        if len(node_ids) != 1:
            raise ValueError("Expected one scalar CU/DU node ID")

        message = indication.msg.frm_3
        ue_reports = list(message.meas_report_per_ue)
        records = []
        sequence = self.reports + 1
        for ue_index, ue in enumerate(ue_reports):
            ue_id = ue.ue_meas_report_lst
            if ue_id.type != ric.GNB_DU_UE_ID_E2SM:
                raise ValueError("Expected gNB-DU UE identity")
            f1ap_id = int(ue_id.gnb_du.gnb_cu_ue_f1ap)
            report = ue.ind_msg_format_1
            periods = list(report.gran_period_ms)
            if len(periods) != 1 or int(periods[0]) <= 0:
                raise ValueError(f"Expected one positive granularity scalar: {periods!r}")
            period = int(periods[0])
            if period != 1000 or len(list(report.meas_data_lst)) != 1:
                raise ValueError("Expected one 1000 ms row per UE report")
            self.monitor.register(420, f1ap_id, RULES)

            for row_index, row in enumerate(report.meas_data_lst):
                if row.meas_record_len != report.meas_info_lst_len:
                    raise ValueError("Measurement names and values do not align")
                start = collected + timedelta(milliseconds=row_index * period)
                end = start + timedelta(milliseconds=period)
                for value, info in zip(
                    row.meas_record_lst, report.meas_info_lst,
                ):
                    if info.meas_type.type != ric.NAME_MEAS_TYPE:
                        raise ValueError("Expected measurement name")
                    name = info.meas_type.name
                    if name not in RULES:
                        raise ValueError(f"Unexpected measurement: {name}")
                    if value.value == ric.INTEGER_MEAS_VALUE:
                        kind, number = "integer", int(value.int_val)
                    elif value.value == ric.REAL_MEAS_VALUE:
                        kind, number = "real", float(value.real_val)
                    else:
                        kind, number = "no_value", ""
                    if number != "" and (
                        not math.isfinite(number) or number < 0
                    ):
                        raise ValueError("Invalid QoS value")

                    records.append([
                        received.isoformat(), sequence,
                        identity.nb_id.nb_id,
                        identity.plmn.mcc, identity.plmn.mnc,
                        int(node_ids[0]), int(ue_id.type), f1ap_id,
                        ue_index, row_index, raw, collected.isoformat(), period,
                        start.isoformat(), end.isoformat(),
                        "header_plus_row_granularity_nominal",
                        int(row.incomplete_flag == ric.TRUE_ENUM_VALUE),
                        name, kind, number, RULES[name][0],
                        number * 1000
                        if number != "" and name.startswith("DRB.UEThp")
                        else "",
                        normalize(name, number) if number != "" else "",
                        RULES[name][1],
                    ])
        if not records:
            raise ValueError("Empty UE measurement report")
        with self.output.open("a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(records)
        for record in records:
            events = self.monitor.observe(
                self.monitor.generation,
                record[2], record[7], record[17], sequence,
                None if record[19] == "" else record[19],
                incomplete=bool(record[16]),
            )
            for event in events:
                self.emit(event)
        self.reports = sequence
        print(f"Recorded metadata report={sequence} rows={len(records)}", flush=True)


def main():
    output = Path(os.environ.get("XAPP_OUTPUT", "/evidence/kpm.csv"))
    result_path = Path(os.environ.get(
        "PROBE_OUTPUT", str(output.with_suffix(".json")),
    ))
    duration = float(os.environ.get("KPM_RECORD_SECONDS", "40"))
    if not 5 <= duration <= 300:
        raise SystemExit("KPM_RECORD_SECONDS must be between 5 and 300")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(FIELDS)

    result = {"passed": False, "cleanup_errors": []}
    callback = Recorder(output)
    handle = None
    initialized = False
    try:
        ric.init(sys.argv)
        initialized = True
        time.sleep(2)
        nodes = [
            node for node in ric.conn_e2_nodes()
            if node.id.nb_id.nb_id == 420
            and ric.get_e2ap_ngran_name(node.id.type) == "ngran_gNB_DU"
        ]
        if len(nodes) != 1:
            raise RuntimeError("Expected one DU node 420")
        handle = ric.report_kpm_sm(
            nodes[0].id, ric.Interval_ms_1000,
            list(RULES), callback,
        )
        if handle < 0:
            handle = None
            raise RuntimeError("Subscription rejected")
        print("METADATA_SUBSCRIPTION_READY", flush=True)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            callback.check_silence()
            time.sleep(0.2)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if handle is not None:
            try:
                ric.rm_report_kpm_sm(handle)
                print("METADATA_DELETE_RETURNED", flush=True)
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
            result["reports"] = callback.reports
            result["callback_errors"] = list(callback.errors)
            result["mode"] = "advisory"
            result["metrics"] = list(RULES)
            result["network_reconnection_tested"] = False
        result["passed"] = (
            "error" not in result
            and not result["cleanup_errors"]
            and not result["callback_errors"]
            and result["reports"] >= 3
        )
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
