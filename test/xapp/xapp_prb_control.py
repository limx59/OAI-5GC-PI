#!/usr/bin/env python3
"""Request hard PRB caps for independent NR scheduler simulations."""

import json
import os
import time
from pathlib import Path

import xapp_kpm as demo
from xapp_slice_policy import allocate

ric = demo.ric


def build_control(plan):
    entries = plan["slices"]
    message = ric.slice_ctrl_msg_t()
    message.type = ric.SLICE_CTRL_SM_V0_ADD
    downlink = ric.ul_dl_slice_conf_t()
    downlink.sched_name = "PF"
    downlink.len_sched_name = 2
    downlink.len_slices = len(entries)
    array = ric.slice_array(len(entries))
    parents = [downlink, array]
    for index, entry in enumerate(entries):
        item = ric.fr_slice_t()
        item.id = index
        item.label = entry["slice_id"]
        item.len_label = len(item.label.encode("utf-8"))
        item.sched = "PF"
        item.len_sched = 2
        item.params.type = ric.SLICE_ALG_SM_V0_NVS
        item.params.u.nvs.conf = ric.SLICE_SM_NVS_V0_CAPACITY
        item.params.u.nvs.u.capacity.u.pct_reserved = (
            entry["recommended_prb_percent"] / 100.0
        )
        array[index] = item
        parents.append(item)
    downlink.slices = array
    message.u.add_mod_slice.dl = downlink
    return message, parents


def main():
    value = os.environ.get("XAPP_SLICE_NODE_ID", "1")
    if not value or any(character not in "0123456789" for character in value):
        raise ValueError("XAPP_SLICE_NODE_ID must be an integer in 1..65535.")
    node_id = int(value)
    if not 1 <= node_id <= 65535:
        raise ValueError("XAPP_SLICE_NODE_ID must be an integer in 1..65535.")

    value = os.environ.get("XAPP_PRB_QUOTAS", "45,40,15")
    parts = value.split(",")
    if (len(parts) != 3 or any(not p or
            any(c not in "0123456789" for c in p) or len(p) > 3
            for p in parts)):
        raise ValueError("XAPP_PRB_QUOTAS requires three integer percentages.")
    quotas = [int(p) for p in parts]
    if any(q > 100 for q in quotas) or sum(quotas) != 100:
        raise ValueError("XAPP_PRB_QUOTAS percentages must sum to 100.")
    plan = {"executed": False, "slices": [
        {"slice_id": label, "recommended_prb_percent": quota}
        for label, quota in zip(("embb", "latency-sensitive", "iot"), quotas)
    ]}
    print("Requested PRB caps:", json.dumps(plan), flush=True)
    message, parents = build_control(plan)

    ric.init(demo.sys.argv)
    try:
        time.sleep(2)
        nodes = ric.conn_e2_nodes()
        matches = [
            node for node in nodes
            if node.id.plmn.mcc == 505
            and node.id.plmn.mnc == 1
            and node.id.plmn.mnc_digit_len == 2
            and node.id.nb_id.nb_id == node_id
            and node.id.type == ric.e2ap_ngran_gNB
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected exactly one lab gNB: PLMN 505/01, ID {node_id}; "
                f"found {len(matches)}. No control sent.")
        print(f"Sending custom SLICE ADD/MOD control to lab node {node_id}.",
              flush=True)
        ric.control_slice_sm(matches[0].id, message)
        time.sleep(5)
        print("Control response received. Verify E2_PRB_EXECUTION and "
              "actual PDSCH evidence at the selected experimental Agent.",
              flush=True)
    finally:
        # Retain message parents until the native SDK has stopped.
        while ric.try_stop == 0:
            time.sleep(1)


if __name__ == "__main__":
    main()
