#!/usr/bin/env python3
"""Record CU-UP node-level PDCP packet-success statistics via KPM."""

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

METRIC = "DRB.PacketSuccessRateUlgNBUu"
FIELDS = ['received_at_utc', 'report_sequence', 'node_id', 'node_type', 'mcc', 'mnc', 'cu_up_id', 'row_index', 'collect_start_ntp64', 'collect_start_utc', 'granularity_ms', 'nominal_window_start_utc', 'nominal_window_end_utc', 'window_basis', 'incomplete', 'measurement', 'value_type', 'value', 'unit', 'measurement_scope', 'statistic_basis']


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

    def handle(self, indication):
        with self.lock:
            try:
                self.record(indication)
            except Exception as error:
                self.errors.append(str(error))
                print(f"CSV callback error: {error}", file=sys.stderr, flush=True)

    def record(self, indication):
        if indication.msg.type != ric.FORMAT_1_INDICATION_MESSAGE:
            raise ValueError("Expected node-level indication Format 1")
        identity = indication.id
        node_type = ric.get_e2ap_ngran_name(identity.type)
        if identity.nb_id.nb_id != 420 or node_type != "ngran_gNB_CUUP":
            raise ValueError("Expected CU-UP node 420")

        received = datetime.now(timezone.utc)
        raw = int(indication.hdr.kpm_ric_ind_hdr_format_1.collectStartTime)
        if -(1 << 63) <= raw < 0:
            raw += 1 << 64
        collected = ntp_utc(raw)
        if abs((received - collected).total_seconds()) > 30:
            raise ValueError(
                f"Header timestamp mismatch: collected={collected.isoformat()}, "
                f"received={received.isoformat()}"
            )
        node_ids = list(identity.cu_du_id)
        if len(node_ids) != 1:
            raise ValueError("Expected one CU-UP component ID")
        cu_up_id = int(node_ids[0])
        if cu_up_id < 0:
            raise ValueError("Invalid CU-UP component ID")

        report = indication.msg.frm_1
        periods = list(report.gran_period_ms)
        if len(periods) != 1 or int(periods[0]) <= 0:
            raise ValueError(f"Expected positive granularity: {periods!r}")
        period = int(periods[0])
        infos = list(report.meas_info_lst)
        if report.meas_info_lst_len != len(infos) or len(infos) != 1:
            raise ValueError("Expected one measurement descriptor")
        if (infos[0].meas_type.type != ric.NAME_MEAS_TYPE
                or infos[0].meas_type.name != METRIC):
            raise ValueError("Unexpected PDCP measurement descriptor")

        sequence = self.reports + 1
        records = []
        for row_index, row in enumerate(report.meas_data_lst):
            values = list(row.meas_record_lst)
            if row.meas_record_len != 1 or len(values) != 1:
                raise ValueError("Expected one PDCP measurement value")
            value = values[0]
            if value.value == ric.INTEGER_MEAS_VALUE:
                kind, number = "integer", int(value.int_val)
            elif value.value == ric.REAL_MEAS_VALUE:
                kind, number = "real", float(value.real_val)
            else:
                kind, number = "no_value", ""
            if number != "" and (
                not math.isfinite(number) or not 0 <= number <= 100
            ):
                raise ValueError(f"Invalid PDCP percentage: {number!r}")
            start = collected + timedelta(milliseconds=row_index * period)
            end = start + timedelta(milliseconds=period)
            records.append([
                received.isoformat(), sequence, identity.nb_id.nb_id,
                node_type, identity.plmn.mcc, identity.plmn.mnc,
                cu_up_id, row_index, raw, collected.isoformat(), period,
                start.isoformat(), end.isoformat(),
                "header_plus_row_granularity_nominal",
                int(row.incomplete_flag == ric.TRUE_ENUM_VALUE),
                METRIC, kind, number, "percent", "CU-UP node",
                "provider_cached_rx_sdu_to_data_pdu_ratio",
            ])
        if not records:
            raise ValueError("Empty node-level measurement report")
        with self.output.open("a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(records)
        self.reports = sequence
        print(f"Recorded metadata report={sequence} rows={len(records)}", flush=True)



def main():
    output = Path(os.environ.get("XAPP_OUTPUT", "/evidence/kpm.csv"))
    result_path = Path(os.environ.get(
        "PROBE_OUTPUT", str(output.with_suffix(".json")),
    ))
    if os.environ.get("OAI_PI_KPM_REPORT_STYLE") != "1":
        raise SystemExit("OAI_PI_KPM_REPORT_STYLE=1 is required")
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
            and ric.get_e2ap_ngran_name(node.id.type) == "ngran_gNB_CUUP"
        ]
        if len(nodes) != 1:
            raise RuntimeError("Expected one CU-UP node 420")
        handle = ric.report_kpm_sm(
            nodes[0].id, ric.Interval_ms_1000,
            [METRIC], callback,
        )
        if handle < 0:
            handle = None
            raise RuntimeError("Subscription rejected")
        print("METADATA_SUBSCRIPTION_READY", flush=True)
        time.sleep(duration)
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
            result["metric"] = METRIC
            result["scope"] = "CU-UP node-level PDCP packet-success delivery"
            result["application_packet_loss_validated"] = False
            result["pdcp_reordering_delay_validated"] = False
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
