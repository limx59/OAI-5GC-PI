#!/usr/bin/env python3
"""Monitor configured MAC, RLC and PDCP reports using FlexRIC."""

import os
import sys
import threading
import time

sys.path.insert(0, os.environ.get(
    "FLEXRIC_SDK_PATH", "/usr/local/lib/python3/dist-packages/xapp_sdk"
))
import xapp_sdk as ric


_LOG_LOCK = threading.Lock()


def write_line(message, stream=None):
    if stream is None:
        stream = sys.stdout
    with _LOG_LOCK:
        stream.write(message + "\n")
        stream.flush()


def print_report(model, indication, field):
    try:
        records = getattr(indication, field)
        write_line(
            f"{model} node={indication.id.nb_id.nb_id} "
            f"records={len(records)} timestamp={indication.tstamp}"
        )
    except Exception as error:
        write_line(f"{model} callback error: {error}",
                   stream=sys.stderr)


class MACCallback(ric.mac_cb):
    def __init__(self):
        ric.mac_cb.__init__(self)

    def handle(self, indication):
        print_report("MAC", indication, "ue_stats")


class RLCCallback(ric.rlc_cb):
    def __init__(self):
        ric.rlc_cb.__init__(self)

    def handle(self, indication):
        print_report("RLC", indication, "rb_stats")


class PDCPCallback(ric.pdcp_cb):
    def __init__(self):
        ric.pdcp_cb.__init__(self)

    def handle(self, indication):
        print_report("PDCP", indication, "rb_stats")


MODELS = {
    "MAC": (MACCallback, ric.report_mac_sm, ric.rm_report_mac_sm),
    "RLC": (RLCCallback, ric.report_rlc_sm, ric.rm_report_rlc_sm),
    "PDCP": (PDCPCallback, ric.report_pdcp_sm, ric.rm_report_pdcp_sm),
}


def main():
    ric.init(sys.argv)
    subscriptions = []
    callbacks = []
    try:
        time.sleep(2)
        nodes = ric.conn_e2_nodes()
        for config in ric.get_cust_sm_conf():
            if config.name not in MODELS:
                continue
            period = str(config.time)
            if not period.endswith("_ms"):
                raise ValueError(f"Unsupported report period: {period}")
            interval = getattr(ric, f"Interval_ms_{period[:-3]}", None)
            if interval is None:
                raise ValueError(f"Unsupported report period: {period}")
            callback_type, subscribe, unsubscribe = MODELS[config.name]
            for node in nodes:
                callback = callback_type()
                callbacks.append(callback)
                handle = subscribe(node.id, interval, callback)
                subscriptions.append((unsubscribe, handle))
                write_line(f"Subscribed: {config.name}, "
                           f"node={node.id.nb_id.nb_id}")
        if subscriptions:
            time.sleep(10)
        else:
            print("No subscriptions: check nodes and custom SM config.",
                  flush=True)
    except KeyboardInterrupt:
        print("Stopping radio statistics demo.", flush=True)
    finally:
        for unsubscribe, handle in subscriptions:
            unsubscribe(handle)
        while ric.try_stop == 0:
            time.sleep(1)


if __name__ == "__main__":
    main()
