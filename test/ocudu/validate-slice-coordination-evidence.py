#!/usr/bin/env python3
"""Accept retained coordination evidence and reject targeted mutations."""
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
    review = runpy.run_path(str(
        ROOT / "test/ocudu/review-slice-coordination-grants.py"
    ))["review"]
    require(review(dest)["passed"] is True, "Original evidence failed")
    original_read = Path.read_bytes
    checks = []

    def log_mutation(phase, old, new):
        selected = dest / f"gnb.{phase}.420.after.json"
        before = json.loads(original_read(
            dest / f"gnb.{phase}.420.before.json"
        ))
        after = json.loads(original_read(selected))
        count = 0
        for stream in ("stdout", "stderr"):
            prefix = before[stream]
            require(after[stream].startswith(prefix), "History mismatch")
            suffix = after[stream][len(prefix):]
            count += suffix.count(old)
            after[stream] = prefix + suffix.replace(old, new)
        require(count > 0, "Missing mutation anchor")
        return selected, json.dumps(after).encode()

    cases = [
        ("DL cap exceeded",
         *log_mutation("node420-high", "rb=[0..10)", "rb=[0..11)"),
         "DL allocation exceeds limited cap"),
        ("DL restoration missing",
         *log_mutation("both-low-1", "rb=[0..11)", "rb=[0..10)"),
         "Restoration did not exceed former cap"),
        ("Scheduler update missing",
         *log_mutation("node420-high",
                       "- Slice Reconfig: cell=0", "- Removed update"),
         "Expected one scheduler update"),
    ]

    selected = dest / "decision.node420-high.1.json"
    record = json.loads(original_read(selected))
    del record["input"]["421"]
    cases.append((
        "Peer report missing", selected, json.dumps(record).encode(),
        "Unexpected fixture demand",
    ))

    selected = dest / "control.node420-high.420.log"
    lines = original_read(selected).decode().splitlines()
    changed = 0
    for i, line in enumerate(lines):
        if not line.startswith("{"):
            continue
        item = json.loads(line)
        if item.get("event") == "request":
            require(item["payload"]["policies"]["max_prb_policy_ratio"] == 20,
                    "Unexpected original control ratio")
            item["payload"]["policies"]["max_prb_policy_ratio"] = 21
            lines[i] = json.dumps(item)
            changed += 1
    require(changed == 1, "Expected one request mutation")
    cases.append((
        "Control ratio inconsistent", selected,
        ("\n".join(lines) + "\n").encode(),
        "Unexpected control payload",
    ))

    for label, selected, replacement, expected in cases:
        def mutated_read(path):
            if path.resolve() == selected.resolve():
                return replacement
            return original_read(path)

        with patch.object(Path, "read_bytes", mutated_read):
            try:
                review(dest)
            except RuntimeError as error:
                require(str(error) == expected,
                        "Rejected for unintended reason: " + str(error))
                checks.append({
                    "case": label, "rejected": True, "reason": str(error),
                })
            else:
                raise RuntimeError("Incorrect evidence accepted: " + label)
        print("PASS: rejected", label, flush=True)
    return {
        "passed": True,
        "evidence": str(dest),
        "original_evidence_accepted": True,
        "negative_checks": checks,
        "control_requests_sent": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    dest = args.evidence.resolve()
    require(dest.is_relative_to(BASE.resolve()) and dest.is_dir(),
            "Unexpected evidence directory")
    report = Path(tempfile.mkdtemp(
        prefix="ocudu-coordination-evidence-check-", dir=BASE
    ))
    report.chmod(0o700)
    result = {"passed": False, "evidence": str(dest)}
    try:
        result = validate(dest)
    except Exception as error:
        result["error"] = str(error)
    finally:
        (report / "summary.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print("Passed:", result["passed"])
        print("SAVED:", report / "summary.json")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
