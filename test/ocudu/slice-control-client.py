#!/usr/bin/env python3
"""Send one cell-level slice policy request and validate its response."""
import argparse
import json
import sys
import websocket


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plmn", default="00101")
    parser.add_argument("--sst", type=int, default=1)
    parser.add_argument("--sd", type=int)
    parser.add_argument("--min-ratio", type=int, required=True)
    parser.add_argument("--max-ratio", type=int, required=True)
    args = parser.parse_args()

    require(args.plmn.isascii() and args.plmn.isdigit()
            and len(args.plmn) in (5, 6), "Invalid PLMN")
    require(0 <= args.sst <= 255, "Invalid SST")
    require(args.sd is None or 0 <= args.sd < 0xffffff, "Invalid SD")
    require(0 <= args.min_ratio <= args.max_ratio <= 100
            and args.max_ratio > 0, "Invalid min/max ratios")

    member = {"plmn": args.plmn, "sst": args.sst}
    if args.sd is not None:
        member["sd"] = args.sd
    request = {
        "cmd": "rrm_policy_ratio_set",
        "policies": {
            "resourceType": "PRB",
            "rRMPolicyMemberList": [member],
            "min_prb_policy_ratio": args.min_ratio,
            "max_prb_policy_ratio": args.max_ratio,
        },
    }
    print(json.dumps({"event": "request", "payload": request}), flush=True)
    connection = websocket.create_connection(
        "ws://127.0.0.1:8001/", timeout=10,
        http_no_proxy=["127.0.0.1", "localhost"],
    )
    try:
        connection.send(json.dumps(request))
        raw = connection.recv()
        require(isinstance(raw, str) and len(raw) <= 65536,
                "Invalid response type or size")
        response = json.loads(raw)
        require(isinstance(response, dict), "Expected JSON response object")
        print(json.dumps({"event": "response", "payload": response}), flush=True)
        require("error" not in response, "Remote command returned an error")
        require(response.get("cmd") == request["cmd"],
                "Response command mismatch")
        require(isinstance(response.get("timestamp"), str)
                and response["timestamp"], "Response timestamp missing")
        print(json.dumps({
            "passed": True,
            "scope": "Remote command response only",
            "requests_sent": 1,
            "scheduler_execution_validated": False,
        }), flush=True)
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"passed": False, "error": str(error)}), flush=True)
        sys.exit(1)
