#!/usr/bin/env python3
"""Audit advertised custom-SM capability without sending subscriptions."""

import json
import os
from pathlib import Path
import sys
import time


CUSTOM_IDS = {"MAC": 142, "RLC": 143, "PDCP": 144}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def classify(functions):
    require(bool(functions), "No advertised RAN functions")
    ids = [item["id"] for item in functions]
    require(all(type(value) is int and 0 <= value <= 65535 for value in ids),
            "Invalid RAN-function ID")
    require(len(ids) == len(set(ids)), "Duplicate RAN-function ID")
    require(all(type(item["revision"]) is int
                and 0 <= item["revision"] <= 65535 for item in functions),
            "Invalid RAN-function revision")
    return {
        name: {
            "ran_function_id": value,
            "advertised": value in ids,
            "delivery_validated": False,
            "decision": ("requires_separate_delivery_test" if value in ids
                         else "unsupported_not_advertised"),
        }
        for name, value in CUSTOM_IDS.items()
    }


def main():
    sys.path.insert(0, os.environ.get(
        "FLEXRIC_SDK_PATH",
        "/usr/local/lib/python3/dist-packages/xapp_sdk",
    ))
    import xapp_sdk as ric

    role = os.environ.get("CAPABILITY_ROLE", "ngran_gNB_DU")
    require(role in ("ngran_gNB_DU", "ngran_gNB_CUUP"), "Invalid test role")
    output = Path(os.environ.get("PROBE_OUTPUT", "/evidence/capability.json"))
    result = {
        "passed": False,
        "scope": "Advertised capability audit; no custom subscriptions",
        "subscription_attempts": 0,
        "custom_sm_delivery_validated": False,
        "original_radio_stats_main_exercised": False,
        "cleanup_errors": [],
    }
    initialized = False
    try:
        ric.init(sys.argv)
        initialized = True
        time.sleep(2)
        nodes = [
            node for node in ric.conn_e2_nodes()
            if node.id.nb_id.nb_id == 420
            and ric.get_e2ap_ngran_name(node.id.type) == role
            and (node.id.plmn.mcc, node.id.plmn.mnc) == (1, 1)
        ]
        require(len(nodes) == 1, "Expected one matching laboratory node")
        node = nodes[0]
        functions = [
            {"id": int(item.id), "revision": int(item.rev)}
            for item in node.ran_func
        ]
        models = classify(functions)
        require(2 in {item["id"] for item in functions},
                "Expected advertised KPM function")
        result.update(
            node_id=420, mcc=1, mnc=1, role=role,
            component_ids=[int(value) for value in node.id.cu_du_id],
            advertised_functions=functions,
            custom_models=models,
            custom_sm_all_advertised=all(
                item["advertised"] for item in models.values()),
        )
        print("CUSTOM_SM_CAPABILITY_CAPTURED", flush=True)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if initialized:
            deadline = time.monotonic() + 15
            while ric.try_stop == 0 and time.monotonic() < deadline:
                time.sleep(0.1)
            if ric.try_stop == 0:
                result["cleanup_errors"].append("SDK shutdown timeout")
        result["passed"] = (
            "error" not in result and not result["cleanup_errors"]
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
