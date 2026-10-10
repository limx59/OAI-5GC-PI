#!/usr/bin/env python3
"""Observe QoS and report silence while an Agent is paused."""

from datetime import datetime, timezone
import os
import threading

import xapp_kpm_recovery as recovery
from xapp_qos_watch import QoSCallback
from qos_report_state import ReportState


def event(label, key):
    print(f"{label}: node={key[0]} metric={key[4]} "
          f"received_utc={datetime.now(timezone.utc).isoformat()}",
          flush=True)


class FaultCallback(QoSCallback):
    def __init__(self):
        super().__init__()
        self.report_state = ReportState(
            float(os.environ.get("XAPP_QOS_REPORT_TIMEOUT", "5")))
        self.failed = False

    def handle(self, indication):
        try:
            self.record(indication)
        except Exception as error:
            self.failed = True
            print(f"QoS callback error: {error}", flush=True)

    def evaluate(self, groups, reporting_node=None):
        # The inherited record() holds report_lock during this call.
        for key in self.report_state.observe(groups):
            event("REPORT_RECOVERY", key)
        super().evaluate(groups, reporting_node)
        for key in groups:
            event("REPORT", key)

    def check_silence(self):
        with self.report_lock:
            for key in self.report_state.expire():
                self.low_counts[key] = 0
                self.alerts.discard(key)
                event("STALE", key)


def main():
    callback = FaultCallback()
    stopped = threading.Event()

    def watchdog():
        while not stopped.wait(0.2):
            try:
                callback.check_silence()
            except Exception as error:
                callback.failed = True
                print(f"QoS watchdog error: {error}", flush=True)
                return

    # Keep one callback alive for all subscriptions.
    recovery.KPMCallback = lambda: callback
    os.environ.setdefault(
        "KPM_RECOVERY_STOP_FILE", "/tmp/qos-fault-stop")
    worker = threading.Thread(target=watchdog, daemon=True)
    worker.start()
    try:
        recovery.main()
    finally:
        stopped.set()
        worker.join(timeout=2)
    if callback.failed:
        raise RuntimeError("QoS monitoring encountered an error.")


if __name__ == "__main__":
    main()
