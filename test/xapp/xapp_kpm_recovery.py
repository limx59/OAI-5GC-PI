#!/usr/bin/env python3
"""Observe persistent KPM subscriptions across a RIC restart."""

import os
from datetime import datetime, timezone
import sys
import time

sys.path.insert(0, os.environ.get(
    "FLEXRIC_SDK_PATH", "/usr/local/lib/python3/dist-packages/xapp_sdk"
))
import xapp_sdk as ric


def print_measurements(report):
    for row in report.meas_data_lst:
        if row.incomplete_flag == ric.TRUE_ENUM_VALUE:
            print("Warning: incomplete measurement record.", flush=True)
        if row.meas_record_len != report.meas_info_lst_len:
            print("Measurement names and values do not align.", flush=True)
            continue
        for value, info in zip(row.meas_record_lst, report.meas_info_lst):
            name = (info.meas_type.name
                    if info.meas_type.type == ric.NAME_MEAS_TYPE
                    else info.meas_type.id)
            if value.value == ric.INTEGER_MEAS_VALUE:
                result = value.int_val
            elif value.value == ric.REAL_MEAS_VALUE:
                result = value.real_val
            else:
                result = "no value"
            print(f"  {name} = {result}", flush=True)


class KPMCallback(ric.kpm_cb):
    def __init__(self):
        ric.kpm_cb.__init__(self)

    def handle(self, indication):
        try:
            print(f"KPM node={indication.id.nb_id.nb_id} "
                  f"received_utc={datetime.now(timezone.utc).isoformat()}",
                  flush=True)
            if indication.msg.type == ric.FORMAT_1_INDICATION_MESSAGE:
                print_measurements(indication.msg.frm_1)
            elif indication.msg.type == ric.FORMAT_3_INDICATION_MESSAGE:
                for index, ue in enumerate(indication.msg.frm_3.meas_report_per_ue):
                    print(f"  UE report index={index}", flush=True)
                    print_measurements(ue.ind_msg_format_1)
            else:
                print(f"Unsupported format: {indication.msg.type}", flush=True)
        except Exception as error:
            print(f"KPM callback error: {error}", file=sys.stderr, flush=True)


def main():
    ric.init(sys.argv)
    subscriptions = []
    callbacks = []
    try:
        time.sleep(2)
        nodes = ric.conn_e2_nodes()
        for config in ric.get_oran_sm_conf():
            if config.name != "KPM":
                continue
            interval = getattr(ric, f"Interval_ms_{config.time}", None)
            if interval is None:
                raise ValueError(f"Unsupported KPM interval: {config.time}")
            actions = [action.name for action in config.actions]
            if not actions:
                raise ValueError("No KPM measurement actions configured.")
            for node in nodes:
                if node.id.type == ric.e2ap_ngran_eNB:
                    continue
                if config.ran_type != ric.get_e2ap_ngran_name(node.id.type):
                    continue
                callback = KPMCallback()
                callbacks.append(callback)
                handle = ric.report_kpm_sm(
                    node.id, interval, actions, callback
                )
                subscriptions.append(handle)
                print(f"Subscribed: node={node.id.nb_id.nb_id}, "
                      f"metrics={actions}", flush=True)
        if subscriptions:
            print(f"READY: persistent subscriptions, pid={os.getpid()}",
                  flush=True)
            deadline = time.monotonic() + 180
            stop_file = os.environ.get(
                "KPM_RECOVERY_STOP_FILE", "/tmp/kpm-recovery-stop")
            while time.monotonic() < deadline:
                if os.path.exists(stop_file):
                    print("STOP: requested normal subscription cleanup",
                          flush=True)
                    break
                time.sleep(0.2)
        else:
            print("No subscriptions: check connected nodes and KPM config.",
                  flush=True)
    except KeyboardInterrupt:
        print("Stopping KPM demo.", flush=True)
    finally:
        for handle in subscriptions:
            ric.rm_report_kpm_sm(handle)
        while ric.try_stop == 0:
            time.sleep(1)


if __name__ == "__main__":
    main()
