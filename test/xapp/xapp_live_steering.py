#!/usr/bin/env python3
"""Recommend steering from controlled live MAC reports on RIC A."""

import json
import os
import time

from xapp_mac_load import LoadCallback, demo
from xapp_traffic_steering import SteeringPolicy


class SteeringCallback(LoadCallback):
    def __init__(self):
        super().__init__()
        self.policy = SteeringPolicy()
        self.latest = {}
        self.used = {}
        self.started = time.monotonic()
        self.last_evaluation = None
        self.cells = {1: "cell-a", 2: "cell-b"}

    def on_load(self, identity, report):
        super().on_load(identity, report)
        node = report["node"]
        if node not in self.cells:
            raise ValueError(f"Unexpected steering node: {node}")
        now = time.monotonic()
        self.latest[node] = (now, identity, report)
        if set(self.latest) != set(self.cells):
            return
        if any(now - entry[0] > 1.0 for entry in self.latest.values()):
            return
        if self.last_evaluation is not None and now - self.last_evaluation < 1.0:
            return
        if any(
            self.used.get(node) == entry[2]["timestamp_us"]
            for node, entry in self.latest.items()
        ):
            return

        sample = {
            "time_s": now - self.started,
            "cells": {
                self.cells[node]: entry[2]["dl"]
                for node, entry in self.latest.items()
            },
        }
        result = self.policy.evaluate(sample)
        self.used = {
            node: entry[2]["timestamp_us"]
            for node, entry in self.latest.items()
        }
        self.last_evaluation = now
        demo.write_line("STEERING: " + json.dumps({
            **result,
            "cells": sample["cells"],
            "model": "controlled_emulator",
            "executed": False,
        }, sort_keys=True))


def main():
    demo.ric.init(demo.sys.argv)
    callback = SteeringCallback()
    subscriptions = []
    try:
        time.sleep(2)
        nodes = demo.ric.conn_e2_nodes()
        if {node.id.nb_id.nb_id for node in nodes} != {1, 2} or len(nodes) != 2:
            raise ValueError("This scenario requires RIC A nodes 1 and 2.")
        configs = [
            config for config in demo.ric.get_cust_sm_conf()
            if config.name == "MAC"
        ]
        if len(configs) != 1 or str(configs[0].time) != "100_ms":
            raise ValueError("This scenario requires one MAC 100_ms configuration.")
        for node in nodes:
            subscriptions.append(demo.ric.report_mac_sm(
                node.id, demo.ric.Interval_ms_100, callback))
            demo.write_line(f"Subscribed: MAC, node={node.id.nb_id.nb_id}")
        demo.write_line(f"READY: live steering, pid={os.getpid()}")
        deadline = time.monotonic() + 180
        stop_file = os.environ.get(
            "STEERING_STOP_FILE", "/tmp/steering-stop")
        while time.monotonic() < deadline:
            if callback.failed:
                raise RuntimeError("Live steering callback failed.")
            if os.path.exists(stop_file):
                demo.write_line("STOP: requested normal subscription cleanup")
                break
            time.sleep(0.2)
    finally:
        for handle in subscriptions:
            demo.ric.rm_report_mac_sm(handle)
        while demo.ric.try_stop == 0:
            time.sleep(1)
    if callback.failed:
        raise RuntimeError("Live steering callback failed.")


if __name__ == "__main__":
    main()
