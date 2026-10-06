#!/usr/bin/env python3
"""Map synthetic steering recommendations to a lab handover request."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from xapp_traffic_steering import SteeringPolicy

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent


def unsigned_id(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer within [0, {maximum}].")
    return value


def load_mapping(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    ue_id = unsigned_id(data["ran_ue_id"], (1 << 64) - 1, "ran_ue_id")
    cells = data["cells"]
    if not isinstance(cells, dict) or len(cells) < 2:
        raise ValueError("Mapping requires at least two cells.")
    for name, cgi in cells.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Cell names must be nonempty strings.")
        unsigned_id(cgi, (1 << 36) - 1, f"CGI for {name}")
    if len(set(cells.values())) != len(cells):
        raise ValueError("Each cell must have a distinct CGI.")
    return ue_id, cells


def select_request(samples, ue_id, cells):
    if not isinstance(samples, list) or not samples:
        raise ValueError("Samples must be a nonempty JSON array.")
    policy = SteeringPolicy()
    requests = []
    # Validate the entire input before allowing any native control call.
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Each sample must be a JSON object.")
        if not isinstance(sample.get("cells"), dict):
            raise ValueError("Each sample requires a cells map.")
        if set(sample["cells"]) - set(cells):
            raise ValueError("Sample contains cells absent from the mapping.")
        result = policy.evaluate(sample)
        if result["status"] == "recommendation":
            requests.append({
                "time_s": result["time_s"],
                "ran_ue_id": ue_id,
                "source_cell": result["source"],
                "target_cell": result["target"],
                "source_nr_cgi": cells[result["source"]],
                "target_nr_cgi": cells[result["target"]],
                "executed": False,
            })
    if not requests:
        return None
    request = requests[0]
    if request["source_nr_cgi"] >> 8 != 1:
        raise ValueError("Selected source must map to lab gNB ID 1.")
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", nargs="?", type=Path,
        default=HERE / "traffic_samples.json",
    )
    parser.add_argument("--mapping", type=Path, default=HERE / "steering_lab.json")
    parser.add_argument("--config", type=Path, default=HERE / "xapp.conf")
    parser.add_argument(
        "--binary", type=Path,
        default=PROJECT_ROOT / "flexric/build-local/oai-pi-xapp/xapp_handover_control",
    )
    parser.add_argument(
        "--send-emulator", action="store_true",
        help="Send one request to the verified lab emulator.",
    )
    args = parser.parse_args()

    try:
        ue_id, cells = load_mapping(args.mapping)
        samples = json.loads(args.input.read_text(encoding="utf-8"))
        request = select_request(samples, ue_id, cells)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))

    if request is None:
        print("No qualifying steering recommendation; no control sent.", flush=True)
        return

    print("Selected first recommendation:", json.dumps(request), flush=True)
    if not args.send_emulator:
        print("Dry run: no RIC connection or control request.", flush=True)
        return

    binary = args.binary.resolve()
    config = args.config.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error(f"Executable not found: {binary}")
    if not config.is_file():
        parser.error(f"Configuration not found: {config}")

    environment = os.environ.copy()
    environment.update(
        XAPP_RAN_UE_ID=str(request["ran_ue_id"]),
        XAPP_SOURCE_NR_CGI=str(request["source_nr_cgi"]),
        XAPP_TARGET_NR_CGI=str(request["target_nr_cgi"]),
    )
    print("Sending one emulator control request; no real handover is performed.",
          flush=True)
    try:
        result = subprocess.run(
            [str(binary), "-c", str(config)],
            env=environment, timeout=20,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit("Control process timed out; inspect RIC and agent logs.")
    if result.returncode != 0:
        raise SystemExit(f"Control process failed: exit status {result.returncode}")
    print("Control process completed. Verify ACK and agent parameters in logs.",
          flush=True)


if __name__ == "__main__":
    main()
