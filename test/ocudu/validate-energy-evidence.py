#!/usr/bin/env python3
"""Reject targeted in-memory mutations of retained energy simulation evidence."""
import argparse
import json
from pathlib import Path
import runpy
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate(dest):
    dest = dest.resolve()
    require(dest.is_relative_to(BASE.resolve()) and dest.is_dir(),
            "Unexpected evidence directory")
    review = runpy.run_path(str(
        ROOT / "test/ocudu/review-energy-advisory.py"
    ))["review"]
    original = review(dest)
    original_read = Path.read_text
    cases = (
        ("wrong recommendation", "results/advisory.jsonl", 3,
         "action", "restore_active_mode", "Unexpected recommendation"),
        ("wrong simulated transition", "results/simulation.jsonl", 3,
         "simulation_mode_after", "active", "Incorrect simulated transition"),
        ("broken state continuity", "results/simulation.jsonl", 4,
         "simulation_mode_before", "active", "Broken simulation state continuity"),
        ("duplicate record sequence", "results/advisory.jsonl", 2,
         "sequence", 2, "Record sequence or timestamp mismatch"),
        ("false real-control claim", "results/simulation.jsonl", 0,
         "real_control_executed", True, "Invalid provenance or execution claim"),
        ("false power-measurement claim", "results/advisory.jsonl", 0,
         "power_saving_measured", True, "Invalid provenance or execution claim"),
    )
    results = []
    for label, name, index, key, value, expected in cases:
        selected = dest / name
        records = [
            json.loads(line)
            for line in original_read(selected).splitlines()
        ]
        require(records[index].get(key) != value, "Mutation has no effect")
        records[index][key] = value
        changed = "".join(json.dumps(record) + "\n" for record in records)

        def mutated(path, *args, **kwargs):
            if path.resolve() == selected:
                return changed
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", mutated):
            try:
                review(dest)
            except RuntimeError as error:
                require(str(error) == expected,
                        f"Unexpected rejection for {label}: {error}")
            else:
                raise RuntimeError("Incorrect evidence accepted: " + label)
        results.append({"case": label, "rejected": True, "reason": expected})
        print("PASS: rejected", label)
    return {
        "evidence": dest.name,
        "review": original,
        "negative_checks": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.evidence)
    output = Path(tempfile.mkdtemp(
        prefix="ocudu-energy-evidence-", dir=BASE
    ))
    output.chmod(0o700)
    path = output / "summary.json"
    with path.open("x") as stream:
        json.dump({"passed": True, **result}, stream, indent=2)
        stream.write("\n")
    path.chmod(0o600)
    print("SAVED:", path)
    print("PASS: retained evidence and six negative checks.")
    print("Original evidence unchanged; no containers or controls started.")


if __name__ == "__main__":
    main()
