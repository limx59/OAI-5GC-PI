#!/usr/bin/env python3
"""Probe rejected KPM subscription followed by normal subscription recovery."""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, os.environ.get(
    "FLEXRIC_SDK_PATH",
    "/usr/local/lib/python3/dist-packages/xapp_sdk",
))
import xapp_sdk as ric


class ProbeCallback(ric.kpm_cb):
    def __init__(self):
        ric.kpm_cb.__init__(self)
        self.reports = 0
        self.errors = []

    def handle(self, indication):
        try:
            if indication.id.nb_id.nb_id != 420:
                raise RuntimeError("Unexpected indication node")
            if indication.msg.type != ric.FORMAT_3_INDICATION_MESSAGE:
                raise RuntimeError("Expected Style 4 indication Format 3")
            self.reports += 1
        except Exception as error:
            self.errors.append(str(error))


def main():
    result = {"passed": False, "scope": "Unsupported metric and subsequent recovery"}
    handles = []
    callbacks = []
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
            raise RuntimeError("Expected exactly one DU node 420")
        node = nodes[0]

        rejected = ProbeCallback()
        callbacks.append(rejected)
        started = time.monotonic()
        handle = ric.report_kpm_sm(
            node.id, ric.Interval_ms_1000,
            ["OAI.PI.UnsupportedMetricForRejectionTest"], rejected,
        )
        result["rejection_elapsed_s"] = time.monotonic() - started
        result["rejected_handle"] = handle
        if handle >= 0:
            handles.append(handle)
            raise RuntimeError("Unsupported metric unexpectedly accepted")
        if handle != -1:
            raise RuntimeError("Unexpected rejection return value")
        time.sleep(1)
        if rejected.reports or rejected.errors:
            raise RuntimeError("Unexpected callback for rejected subscription")
        print("PASS: unsupported metric returned -1 without process exit", flush=True)

        valid = ProbeCallback()
        callbacks.append(valid)
        handle = ric.report_kpm_sm(
            node.id, ric.Interval_ms_1000,
            ["DRB.UEThpDl", "DRB.UEThpUl"], valid,
        )
        if handle < 0:
            raise RuntimeError("Normal subscription failed after rejection")
        handles.append(handle)
        time.sleep(6)
        result["recovery_reports"] = valid.reports
        result["callback_errors"] = valid.errors
        if valid.errors or valid.reports < 3:
            raise RuntimeError("Normal reporting did not recover")
        ric.rm_report_kpm_sm(handle)
        handles.remove(handle)
        print("PASS: subsequent normal subscription received reports; delete requested",
              flush=True)
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        cleanup_errors = []
        for handle in handles:
            try:
                ric.rm_report_kpm_sm(handle)
            except Exception as error:
                cleanup_errors.append(str(error))
        if initialized:
            deadline = time.monotonic() + 15
            while ric.try_stop == 0 and time.monotonic() < deadline:
                time.sleep(0.2)
            if ric.try_stop == 0:
                cleanup_errors.append("SDK shutdown did not complete")
        result["cleanup_errors"] = cleanup_errors
        if cleanup_errors:
            result["passed"] = False
        output = Path(os.environ.get("PROBE_OUTPUT", "/evidence/probe.json"))
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
