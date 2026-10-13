#!/usr/bin/env python3
"""List connected E2 nodes. Accept FlexRIC SDK options such as -c CONFIG."""

import os
import sys
import time

sys.path.insert(0, os.environ.get(
    "FLEXRIC_SDK_PATH", "/usr/local/lib/python3/dist-packages/xapp_sdk"
))
import xapp_sdk as ric

RAN_TYPES = {0: "eNB", 2: "gNB", 5: "gNB-CU", 7: "gNB-DU"}


def main():
    ric.init(sys.argv)
    try:
        time.sleep(2)
        nodes = ric.conn_e2_nodes()
        print(f"Connected E2 nodes: {len(nodes)}", flush=True)
        print("INDEX NODE_ID MCC MNC RAN_TYPE", flush=True)
        for index, node in enumerate(nodes):
            identity = node.id
            print(
                index, identity.nb_id.nb_id,
                identity.plmn.mcc, identity.plmn.mnc,
                RAN_TYPES.get(identity.type, f"unknown({identity.type})"),
                flush=True,
            )
        if not nodes:
            print("Start an E2 agent and retry.", flush=True)
    finally:
        # Use the shutdown protocol from the installed SDK's examples.
        while ric.try_stop == 0:
            time.sleep(1)


if __name__ == "__main__":
    main()
