#!/usr/bin/env python3
"""Measure controlled emulator MAC load; no E2 control."""

import json
import threading
import traceback

import xapp_radio_stats as demo

# Dedicated emulator model: 106 PRBs per 500 microseconds.
CAPACITY_PRB_PER_US = 106 / 500


class LoadCallback(demo.ric.mac_cb):
    def __init__(self):
        demo.ric.mac_cb.__init__(self)
        self.lock = threading.Lock()
        self.previous = {}
        self.failed = False

    def handle(self, indication):
        try:
            with self.lock:
                identity = indication.id
                key = (identity.nb_id.nb_id, identity.plmn.mcc,
                       identity.plmn.mnc, identity.type)
                timestamp = int(indication.tstamp)
                records = indication.ue_stats
                if len(records) != 1:
                    raise ValueError("Controlled model requires exactly one UE.")
                record = records[0]
                current = (timestamp, int(record.rnti),
                           int(record.dl_aggr_prb), int(record.ul_aggr_prb))
                previous = self.previous.get(key)
                self.previous[key] = current
                if previous is None:
                    return
                elapsed = current[0] - previous[0]
                if elapsed <= 0 or current[1] != previous[1]:
                    raise ValueError("Invalid timestamp or changed UE identity.")
                loads = {}
                for name, index in (("dl", 2), ("ul", 3)):
                    # Dedicated model uses a wrapping uint32_t counter.
                    delta = (current[index] - previous[index]) % (1 << 32)
                    value = delta / (elapsed * CAPACITY_PRB_PER_US)
                    if not 0 <= value <= 1.001:
                        raise ValueError(f"Load outside model capacity: {value}")
                    loads[name] = min(value, 1.0)
                self.on_load(key, {
                    "node": key[0], "timestamp_us": timestamp,
                    "elapsed_us": elapsed, "rnti": current[1],
                    "model": "controlled_emulator",
                    **loads,
                })
        except BaseException as error:
            self.failed = True
            traceback.print_exc(file=demo.sys.stderr)
            demo.write_line(f"MAC load callback error: {error}",
                            stream=demo.sys.stderr)


    def on_load(self, identity, report):
        """Receive a valid load report while the callback lock is held."""
        demo.write_line("LOAD: " + json.dumps(report, sort_keys=True))


def main():
    callback = LoadCallback()
    # Keep one callback for every node; maintain state by full node identity.
    demo.MODELS = {
        "MAC": (lambda: callback,
                demo.ric.report_mac_sm, demo.ric.rm_report_mac_sm),
    }
    demo.main()
    if callback.failed:
        raise RuntimeError("MAC load collection failed.")


if __name__ == "__main__":
    main()
