#!/usr/bin/env python3
"""Review closed-loop evidence and reject targeted in-memory mutations."""
import argparse
import json
from pathlib import Path
import re
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
        ROOT / "test/ocudu/review-slice-closed-loop-grants.py"
    ))["review"]
    original = review(dest)
    original_read = Path.read_text
    cases = (
        ("DL cap exceeded", "cap", "Actual DL cap not demonstrated"),
        ("DL restoration missing", "restore",
         "Actual DL restoration not demonstrated"),
        ("scheduler update missing", "event",
         "Expected one scheduler update"),
        ("report expired", "stale",
         "Invalid or stale host query interval"),
        ("peer report missing", "peer", "Both node reports required"),
        ("duplicate control executed", "duplicate",
         "Unexpected duplicate execution"),
    )
    checks = []
    for label, kind, expected in cases:
        overrides = {}
        if kind in ("cap", "restore", "event"):
            generation = 2 if kind == "restore" else 1
            tag = f"live-generation{generation}.attempt1.420"
            before = json.loads(original_read(
                dest / f"gnb.{tag}.before.json"
            ))
            selected = dest / f"gnb.{tag}.after.json"
            after = json.loads(original_read(selected))
            changes = 0
            for stream in ("stdout", "stderr"):
                prefix = before[stream]
                require(after[stream].startswith(prefix), "History mismatch")
                delta = after[stream][len(prefix):]
                if kind == "event":
                    changed = delta.replace("- Slice Reconfig: cell=0", "", 1)
                    changes += int(changed != delta)
                else:
                    pattern = r"(UE PDSCH:[^\n]*?\brb=)\[\d+\.\.\d+\)"
                    width = 11 if kind == "cap" else 10
                    changed, count = re.subn(
                        pattern, lambda m: m[1] + f"[0..{width})", delta
                    )
                    changes += count
                after[stream] = prefix + changed
            require(changes > 0, "Mutation did not affect evidence")
            overrides[selected] = json.dumps(after)
        elif kind in ("stale", "peer"):
            selected = dest / "queue-decision.2.json"
            item = json.loads(original_read(selected))
            if kind == "stale":
                item["decision_time_s"] = max(
                    r["host_query_end_s"] for r in item["reports"].values()
                ) + 8
            else:
                del item["reports"]["421"]
            overrides[selected] = json.dumps(item)
        else:
            selected = dest / "queue-control.5.json"
            item = json.loads(original_read(selected))
            item["executed"] = True
            overrides[selected] = json.dumps(item)

        def mutated(path, *args, **kwargs):
            resolved = path.resolve()
            if resolved in overrides:
                return overrides[resolved]
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", mutated):
            try:
                review(dest)
            except (RuntimeError, ValueError) as error:
                require(str(error) == expected,
                        f"Unexpected rejection for {label}: {error}")
            else:
                raise RuntimeError("Incorrect evidence accepted: " + label)
        checks.append({"case": label, "rejected": True, "reason": expected})
        print("PASS: rejected", label)
    return {"evidence": dest.name, "review": original, "negative_checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    rounds = []
    for dest in args.evidence:
        print("\nReview:", dest.name, flush=True)
        rounds.append(validate(dest))
    output = Path(tempfile.mkdtemp(
        prefix="ocudu-closed-loop-evidence-", dir=BASE
    ))
    output.chmod(0o700)
    report = output / "summary.json"
    with report.open("x") as stream:
        json.dump({"passed": True, "rounds": rounds}, stream, indent=2)
        stream.write("\n")
    report.chmod(0o600)
    print("SAVED:", report)
    print("PASS: original evidence and negative checks; no traffic or controls.")


if __name__ == "__main__":
    main()
