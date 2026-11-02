#!/usr/bin/env python3
"""Discover laboratory CU-CP RC advertisement; send no requests."""
import json
import os
from pathlib import Path
import sys
import time

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    sys.path.insert(0, os.environ.get(
        "FLEXRIC_SDK_PATH",
        "/usr/local/lib/python3/dist-packages/xapp_sdk",
    ))
    import xapp_sdk as ric

    output = Path(os.environ.get(
        "PROBE_OUTPUT", "/evidence/rc-capability.json"))
    expected_id = int(os.environ["EXPECTED_RC_FUNCTION_ID"])
    require(0 <= expected_id <= 65535, "Invalid expected RC function ID")
    require(expected_id != 2, "RC and KPM function IDs must differ")

    result = {
        "passed": False,
        "scope": "CU-CP advertised RC function and control style/action discovery",
        "expected_rc_function_id": expected_id,
        "subscription_attempts": 0,
        "control_attempts": 0,
        "control_ack_validated": False,
        "handover_execution_validated": False,
        "control_style_action_validated": False,
        "cleanup_errors": [],
    }
    initialized = False
    try:
        ric.init(sys.argv)
        initialized = True
        deadline = time.monotonic() + 15
        nodes = []
        while time.monotonic() < deadline:
            discovered = ric.conn_e2_nodes()
            result["discovered_nodes"] = [
                {
                    "node_id": int(item.id.nb_id.nb_id),
                    "role": ric.get_e2ap_ngran_name(item.id.type),
                    "mcc": int(item.id.plmn.mcc),
                    "mnc": int(item.id.plmn.mnc),
                    "component_ids": [int(value) for value in item.id.cu_du_id],
                    "advertised_functions": [
                        {"id": int(function.id), "revision": int(function.rev)}
                        for function in item.ran_func
                    ],
                }
                for item in discovered
            ]
            nodes = [
                node for node in discovered
                if node.id.nb_id.nb_id == 420
                and ric.get_e2ap_ngran_name(node.id.type) == "ngran_gNB"
                and (node.id.plmn.mcc, node.id.plmn.mnc) == (1, 1)
            ]
            if nodes:
                break
            time.sleep(0.5)
        require(len(nodes) == 1, "Expected one matching CU-CP laboratory node")
        node = nodes[0]
        functions = [
            {"id": int(item.id), "revision": int(item.rev)}
            for item in node.ran_func
        ]
        ids = [item["id"] for item in functions]
        require(len(ids) == len(set(ids)), "Duplicate RAN function ID")
        require(all(0 <= value <= 65535 for value in ids),
                "Invalid RAN function ID")
        require(all(0 <= item["revision"] <= 65535 for item in functions),
                "Invalid RAN function revision")
        require(expected_id in ids, "Expected RC function not advertised")
        require(
            next(item["revision"] for item in functions
                 if item["id"] == expected_id) == 0,
            "Unexpected RC function revision",
        )
        function = next(
            item for item in node.ran_func if int(item.id) == expected_id)
        encoded = function.rc_definition_json
        require(isinstance(encoded, str) and 0 < len(encoded) <= 1048576,
                "Missing decoded RC definition from SDK")
        description = json.loads(encoded)
        result["decoded_function_definition"] = description
        result["definition_source"] = (
            "Connected node RC RAN Function Definition decoded by SDK; "
            "exported by laboratory SWIG patch"
        )
        with (output.parent / "rc-function-definition.json").open("x") as stream:
            json.dump(description, stream, indent=2)
            stream.write("\n")
        require(description["control_present"] is True,
                "Control styles not advertised")
        styles = [
            item for item in description["styles"]
            if item["style_type"] == 3
        ]
        require(len(styles) == 1, "Expected exactly one control Style 3")
        style = styles[0]
        require(style["header_format"] == 1
                and style["message_format"] == 1,
                "Unexpected Style 3 header/message formats")
        require(sum(item["id"] == 1 for item in style["actions"]) == 1,
                "Expected exactly one Style 3 Action 1")
        result["control_style_action_validated"] = True
        result.update(
            node_id=420, mcc=1, mnc=1, role="ngran_gNB",
            component_ids=[int(value) for value in node.id.cu_du_id],
            advertised_functions=functions,
            rc_function_advertised=True,
            cu_cp_identity_validated=False,
            identity_note=(
                "SDK reports ngran_gNB; CU-CP identity requires "
                "validator configuration and E2-CU-CP log evidence"
            ),
        )
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
            "error" not in result and not result["cleanup_errors"])
        with output.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
