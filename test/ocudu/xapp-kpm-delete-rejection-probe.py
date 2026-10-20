#!/usr/bin/env python3
"""Probe continued reporting after delete rejection and a successful retry."""

from datetime import datetime, timezone
import json
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


def now():
    return datetime.now(timezone.utc).isoformat()


class ProbeCallback(ric.kpm_cb):
    def __init__(self):
        ric.kpm_cb.__init__(self)
        self.lock = threading.Lock()
        self.reports = []
        self.errors = []

    def handle(self, indication):
        received = (time.monotonic(), now())
        try:
            if indication.id.nb_id.nb_id != 420:
                raise RuntimeError("Unexpected indication node")
            if indication.msg.type != ric.FORMAT_3_INDICATION_MESSAGE:
                raise RuntimeError("Expected Style 4 indication Format 3")
            with self.lock:
                self.reports.append(received)
        except Exception as error:
            with self.lock:
                self.errors.append(str(error))

    def snapshot(self):
        with self.lock:
            return list(self.reports), list(self.errors)


def main():
    result = {
        "passed": False,
        "scope": "Injected delete rejection, continued reports and retry",
        "requires_external_checks": [
            "First deletion receives FAILURE",
            "Second deletion receives RESPONSE",
            "gNB sends no indications later than the deletion grace period",
        ],
    }
    initialized = False
    handle = None
    callback = ProbeCallback()
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
        handle = ric.report_kpm_sm(
            nodes[0].id, ric.Interval_ms_1000,
            ["DRB.UEThpDl", "DRB.UEThpUl"], callback,
        )
        result["handle"] = handle
        if handle < 0:
            handle = None
            raise RuntimeError("Normal subscription rejected")

        time.sleep(6)
        reports, errors = callback.snapshot()
        result["initial_reports"] = len(reports)
        if errors or len(reports) < 3:
            raise RuntimeError("Initial reporting failed")

        result["first_delete_started_utc"] = now()
        started = time.monotonic()
        ric.rm_report_kpm_sm(handle)
        first_returned = time.monotonic()
        result["first_delete_returned_utc"] = now()
        result["first_delete_elapsed_s"] = first_returned - started
        print("PROBE_FIRST_DELETE_RETURNED", flush=True)

        time.sleep(6)
        reports, errors = callback.snapshot()
        continued = [
            stamp for stamp, _ in reports
            if stamp > first_returned + 1
        ]
        result["reports_after_first_delete_grace"] = len(continued)
        if errors or len(continued) < 3:
            raise RuntimeError("Reporting did not continue after first deletion")

        result["retry_delete_started_utc"] = now()
        started = time.monotonic()
        ric.rm_report_kpm_sm(handle)
        deleted = time.monotonic()
        result["retry_delete_returned_utc"] = now()
        result["retry_delete_elapsed_s"] = deleted - started
        handle = None
        print("PROBE_RETRY_DELETE_RETURNED", flush=True)

        time.sleep(7)
        reports, errors = callback.snapshot()
        observed = time.monotonic()
        result["observed_until_utc"] = now()
        result["post_delete_guard_s"] = observed - deleted - 1
        result["late_callbacks"] = [
            utc for stamp, utc in reports if stamp > deleted + 1
        ]
        result["receive_timestamps_utc"] = [utc for _, utc in reports]
        result["callback_errors"] = errors
        if errors or result["late_callbacks"]:
            raise RuntimeError("Callback errors or reports after final deletion")
        if result["post_delete_guard_s"] < 5:
            raise RuntimeError("Insufficient post-delete observation")
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        cleanup_errors = []
        if handle is not None:
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
