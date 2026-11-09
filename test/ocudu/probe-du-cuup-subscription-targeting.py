
from collections import Counter
import json
import os
import sys
import threading
import time

import xapp_kpm as demo

ric = demo.ric
role = os.environ["TARGET_ROLE"]
metric = os.environ["TARGET_METRIC"]
expected = Counter({"ngran_gNB_DU": 1, "ngran_gNB_CUUP": 1, "ngran_gNB": 1})


class Callback(ric.kpm_cb):
    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.reports = 0
        self.unexpected = []

    def handle(self, indication):
        with self.lock:
            try:
                seen = {
                    "gnb_id": int(indication.id.nb_id.nb_id),
                    "role": ric.get_e2ap_ngran_name(indication.id.type),
                }
                if seen == {"gnb_id": 420, "role": role}:
                    self.reports += 1
                else:
                    self.unexpected.append(seen)
            except Exception as exc:
                self.unexpected.append({"error": str(exc)})
            if self.reports >= 3 or self.unexpected:
                self.ready.set()


callback = Callback()
nodes = []
handle = None
initialized = False
error = None
cleanup_errors = []

try:
    ric.init(sys.argv)
    initialized = True
    deadline = time.monotonic() + 10
    while True:
        snapshot = list(ric.conn_e2_nodes())
        nodes = [
            {
                "gnb_id": int(node.id.nb_id.nb_id),
                "role": ric.get_e2ap_ngran_name(node.id.type),
                "ran_function_ids": sorted(int(item.id) for item in node.ran_func),
            }
            for node in snapshot
        ]
        roles = Counter(node["role"] for node in nodes if node["gnb_id"] == 420)
        if roles == expected:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Expected all three Agent roles in one snapshot")
        time.sleep(0.25)

    targets = [
        node for node, item in zip(snapshot, nodes)
        if item["gnb_id"] == 420 and item["role"] == role
        and 2 in item["ran_function_ids"]
    ]
    if len(targets) != 1:
        raise RuntimeError(f"Expected one KPM-capable target for {role}")

    candidate = ric.report_kpm_sm(
        targets[0].id, ric.Interval_ms_1000, [metric], callback
    )
    if candidate < 0:
        raise RuntimeError("KPM subscription rejected")
    handle = candidate
    if not callback.ready.wait(20):
        raise RuntimeError("Timed out waiting for three target reports")
except Exception as exc:
    error = str(exc)
finally:
    if handle is not None:
        try:
            ric.rm_report_kpm_sm(handle)
        except Exception as exc:
            cleanup_errors.append(str(exc))
    if initialized:
        deadline = time.monotonic() + 10
        while ric.try_stop == 0 and time.monotonic() < deadline:
            time.sleep(0.1)
        if ric.try_stop == 0:
            cleanup_errors.append("SDK shutdown timeout")

    with callback.lock:
        result = {
            "passed": error is None and callback.reports >= 3
                      and not callback.unexpected and not cleanup_errors,
            "nodes": nodes,
            "target_role": role,
            "metric": metric,
            "reports": callback.reports,
            "unexpected_sources": callback.unexpected,
            "error": error,
            "cleanup_errors": cleanup_errors,
        }
        print(json.dumps(result), flush=True)

sys.exit(0 if result["passed"] else 1)
