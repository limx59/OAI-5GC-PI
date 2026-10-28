#!/usr/bin/env python3
"""Exercise the unchanged shared KPM recorder against one OCUDU role."""

import csv
import json
import math
import os
from pathlib import Path
import sys
import time
import threading

import xapp_kpm as demo
import xapp_kpm_recorder as recorder

ric = demo.ric


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class CheckedRecorder(recorder.RecorderCallback):
    def __init__(self, node_id, role, metrics):
        super().__init__()
        self.node_id = node_id
        self.role = role
        self.metrics = metrics
        self.errors = []
        self.record_lock = threading.Lock()
        self.closed = False
        self.numeric = {name: 0 for name in metrics}

    def handle(self, indication):
        with self.record_lock:
            if self.closed:
                return
            self.handle_locked(indication)

    def handle_locked(self, indication):
        try:
            require(indication.id.nb_id.nb_id == self.node_id,
                    "Unexpected node ID")
            require(ric.get_e2ap_ngran_name(indication.id.type) == self.role,
                    "Unexpected node role")
            expected = (ric.FORMAT_3_INDICATION_MESSAGE
                        if self.role == "ngran_gNB_DU"
                        else ric.FORMAT_1_INDICATION_MESSAGE)
            require(indication.msg.type == expected,
                    "Unexpected indication format")
            self.record(indication)
        except Exception as error:
            self.errors.append(str(error))
            print(f"COMPATIBILITY_CALLBACK_ERROR: {error}", flush=True)

    def write_records(self, records):
        require(bool(records), "Empty measurement report")
        require({row[9] for row in records} == self.metrics,
                "Missing or unexpected measurements")
        for row in records:
            require(row[8] in (0, 1), "Invalid incomplete flag")
            if row[10] == "no_value":
                require(row[11] == "", "Missing value must remain empty")
            else:
                require(row[10] in ("integer", "real"),
                        "Unknown value type")
                value = float(row[11])
                require(math.isfinite(value) and value >= 0,
                        "Invalid numeric measurement")
                if row[9] == "DRB.PacketSuccessRateUlgNBUu":
                    require(value <= 100, "Success rate exceeds 100")
                if not row[8]:
                    self.numeric[row[9]] += 1
        super().write_records(records)


def main():
    role = os.environ.get("COMPATIBILITY_ROLE", "ngran_gNB_DU")
    require(role in ("ngran_gNB_DU", "ngran_gNB_CUUP"),
            "Unsupported test role")
    node_id = int(os.environ.get("COMPATIBILITY_NODE_ID", "420"))
    duration = float(os.environ.get("KPM_RECORD_SECONDS", "40"))
    require(math.isfinite(duration) and 5 <= duration <= 300,
            "Invalid recording duration")
    metrics = ({"DRB.UEThpDl", "DRB.UEThpUl"}
               if role == "ngran_gNB_DU"
               else {"DRB.PacketSuccessRateUlgNBUu"})
    output = recorder.OUTPUT
    summary_path = Path(os.environ.get("PROBE_OUTPUT", "/evidence/probe.json"))
    result = {"passed": False, "role": role, "cleanup_errors": []}
    callback = CheckedRecorder(node_id, role, metrics)
    handle = None
    initialized = False
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(recorder.FIELDS)
        ric.init(sys.argv)
        initialized = True
        time.sleep(2)
        nodes = [
            node for node in ric.conn_e2_nodes()
            if node.id.nb_id.nb_id == node_id
            and ric.get_e2ap_ngran_name(node.id.type) == role
        ]
        require(len(nodes) == 1, "Expected exactly one matching node")
        candidate = ric.report_kpm_sm(
            nodes[0].id, ric.Interval_ms_1000, sorted(metrics), callback)
        require(candidate >= 0, "Subscription rejected")
        handle = candidate
        print("COMPATIBILITY_SUBSCRIPTION_READY", flush=True)
        time.sleep(duration)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if handle is not None:
            try:
                ric.rm_report_kpm_sm(handle)
            except Exception as error:
                result["cleanup_errors"].append(str(error))
        if initialized:
            deadline = time.monotonic() + 15
            while ric.try_stop == 0 and time.monotonic() < deadline:
                time.sleep(0.1)
            if ric.try_stop == 0:
                result["cleanup_errors"].append("SDK shutdown timeout")
        # Close recording and freeze all counters atomically.
        # A callback already in progress finishes before this snapshot.
        with callback.record_lock:
            callback.closed = True
            reports = callback.report_count
            numeric = dict(callback.numeric)
            errors = list(callback.errors)
        result["recording_boundary"] = (
            "Locked close after SDK shutdown wait; later callbacks ignored"
        )
        result.update(
            reports=reports,
            complete_numeric_samples=numeric,
            callback_errors=errors,
            shared_recorder_reused=True,
            shared_subscription_demo_exercised=False,
        )
        result["passed"] = (
            "error" not in result
            and not result["cleanup_errors"]
            and not result["callback_errors"]
            and reports >= 5
            and all(count >= 3 for count in numeric.values())
        )
        summary_path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
