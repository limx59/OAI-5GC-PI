#!/usr/bin/env python3
"""Send advisory budgets to the lab emulator using custom SLICE control."""

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

    source = Path(os.environ.get(
        "XAPP_SLICE_INPUT",
        str(Path(__file__).with_name("slice_samples.json")),
    )).expanduser()
    plan = allocate(json.loads(source.read_text(encoding="utf-8")))
    if any(s["recommended_prb_percent"] <= 0 for s in plan["slices"]):
        raise ValueError("This control demo requires positive slice budgets.")
    print("Proposed budgets:", json.dumps(plan), flush=True)
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
        print("Check the xApp response and emulator receive log. "
              "The emulator does not apply scheduler changes.", flush=True)
    finally:
        # Retain message parents until the native SDK has stopped.
        while ric.try_stop == 0:
            time.sleep(1)


if __name__ == "__main__":
    main()
