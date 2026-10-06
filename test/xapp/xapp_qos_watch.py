#!/usr/bin/env python3
"""Flag sustained low mean throughput per node using KPM reports."""

import math
import os
from collections import defaultdict

import xapp_kpm as demo
from xapp_kpm_recorder import RecorderCallback

THRESHOLD = float(os.environ.get("XAPP_QOS_THRESHOLD", "6"))
LOW_REPORTS = int(os.environ.get("XAPP_QOS_LOW_REPORTS", "3"))

if not math.isfinite(THRESHOLD) or THRESHOLD < 0:
    raise ValueError("XAPP_QOS_THRESHOLD must be finite and nonnegative.")
if LOW_REPORTS < 1:
    raise ValueError("XAPP_QOS_LOW_REPORTS must be a positive integer.")

TRACKED_METRICS = {"DRB.UEThpDl", "DRB.UEThpUl"}


class QoSCallback(RecorderCallback):
    def __init__(self):
        super().__init__()
        self.low_counts = defaultdict(int)
        self.alerts = set()

    def write_records(self, records):
        groups = defaultdict(list)
        for row in records:
            metric = row[9]
            if metric not in TRACKED_METRICS or row[8]:
                continue
            if row[10] not in ("integer", "real"):
                continue
            value = float(row[11])
            if math.isfinite(value) and value >= 0:
                key = (row[1], row[2], row[3], row[4], metric)
                groups[key].append(value)
        self.evaluate(groups)

    def evaluate(self, groups):
        for key in set(self.low_counts) - set(groups):
            self.low_counts[key] = 0
            if key in self.alerts:
                self.alerts.remove(key)
                print(f"UNKNOWN: node={key[0]} metric={key[4]} "
                      "has no valid measurements.", flush=True)

        for key, values in groups.items():
            mean = sum(values) / len(values)
            label = f"node={key[0]} metric={key[4]}"
            print(f"QoS: {label} mean={mean:.3f} "
                  f"samples={len(values)}", flush=True)
            if mean < THRESHOLD:
                self.low_counts[key] += 1
                if self.low_counts[key] >= LOW_REPORTS and key not in self.alerts:
                    self.alerts.add(key)
                    print(f"ALERT: {label} below {THRESHOLD} for "
                          f"{self.low_counts[key]} consecutive reports.",
                          flush=True)
            else:
                self.low_counts[key] = 0
                if key in self.alerts:
                    self.alerts.remove(key)
                    print(f"RECOVERY: {label} reached {THRESHOLD}.",
                          flush=True)


def main():
    print(f"QoS threshold={THRESHOLD} in agent-reported units; "
          f"required consecutive reports={LOW_REPORTS}.", flush=True)
    demo.KPMCallback = QoSCallback
    demo.main()


if __name__ == "__main__":
    main()
