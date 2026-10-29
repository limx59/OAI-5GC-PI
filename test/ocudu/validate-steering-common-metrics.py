#!/usr/bin/env python3
"""Validate common throughput mapping and unchanged steering policy rules."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import runpy

from steering_common_metrics import convert


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oai-csv", type=Path, required=True)
    parser.add_argument("--ocudu-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    require(not args.output.exists(), "Output directory already exists")
    args.output.mkdir(parents=True)
    result = {"passed": False}
    try:
        policy_path = root / "test/xapp/xapp_traffic_steering.py"
        policy = runpy.run_path(str(policy_path))["SteeringPolicy"]
        checker = runpy.run_path(str(
            root / "test/ocudu/check-steering-policy-rules.py"
        ))["check"]
        result["policy"] = checker(policy)
        result["policy_sha256"] = hashlib.sha256(
            policy_path.read_bytes()
        ).hexdigest()
        result["inputs"] = {}
        for system, source in (
            ("oai", args.oai_csv), ("ocudu", args.ocudu_csv),
        ):
            with source.open(newline="") as stream:
                rows = [
                    row for row in csv.DictReader(stream)
                    if row["measurement"] in ("DRB.UEThpDl", "DRB.UEThpUl")
                ]
            require(bool(rows), f"{system}: no throughput rows")
            mapped = [convert(row, system) for row in rows]
            require({item["direction"] for item in mapped}
                    == {"uplink", "downlink"}, "Missing traffic direction")
            require(all(
                item["normalized_cell_load"] is None
                and not item["eligible_for_normalized_load_policy"]
                for item in mapped
            ), "Throughput incorrectly treated as cell utilization")
            with (args.output / f"{system}-common.jsonl").open("x") as stream:
                for item in mapped:
                    stream.write(json.dumps(item, sort_keys=True) + "\n")
            result["inputs"][system] = {
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "mapped_rows": len(mapped),
                "time_basis": sorted({item["time_basis"] for item in mapped}),
                "source_basis": sorted({item["source_basis"] for item in mapped}),
            }
        result.update(
            passed=True,
            scope="Retained CSV throughput mapping and controlled policy rules",
            common_unit="bit/s",
            live_dual_node_validated=False,
            cross_vendor_prb_mapping_validated=False,
            control_executed=False,
        )
    except Exception as error:
        result["error"] = str(error)
    finally:
        (args.output / "summary.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(json.dumps(result, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
