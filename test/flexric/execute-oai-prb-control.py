#!/usr/bin/env python3
"""Verify actual NR benchmark grants for one received E2 slice command."""
from collections import defaultdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

def main():
    quotas = [int(value) for value in sys.argv[1:]]
    if len(quotas) != 3 or any(q < 0 or q > 100 for q in quotas) or sum(quotas) != 100:
        raise RuntimeError("Invalid received quotas")
    output = Path(tempfile.mkdtemp(prefix="e2-prb-execution-", dir="/tmp"))
    summary = {"passed": False, "quotas": quotas,
               "node": os.environ.get("FLEXRIC_EMULATOR_NB_ID", "default"),
               "scope": "One independent real NR DL scheduler simulation"}
    try:
        env = os.environ.copy()
        env["OAI_PRB_QUOTAS"] = ",".join(map(str, quotas))
        result = subprocess.run(
            ["/opt/oai-prb-bench/bin/nr_dlbench",
             "-u", "3", "-R", "106", "-n", "200", "-L", "0"],
            env=env, capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL)
        text = result.stdout + result.stderr
        (output / "scheduler.log").write_text(text)
        if result.returncode != 0 or "Done." not in text:
            raise RuntimeError("Scheduler execution failed")
        policies = {}
        grants = defaultdict(list)
        for line in text.splitlines():
            if line.startswith("PRB_POLICY "):
                item = json.loads(line[len("PRB_POLICY "):])
                key = (item["frame"], item["slot"])
                if key in policies:
                    raise RuntimeError("Duplicate policy record")
                policies[key] = item
            elif line.startswith("PRB_GRANT "):
                item = json.loads(line[len("PRB_GRANT "):])
                grants[(item["frame"], item["slot"])].append(item)
        if not policies or not grants or not set(grants).issubset(policies):
            raise RuntimeError("Missing scheduler execution evidence")
        totals = [0, 0, 0]
        for key, policy in policies.items():
            actual = [0, 0, 0]
            items = grants.get(key, [])
            for g in items:
                s = g["rnti"] - 0x1234
                if not 0 <= s < 3:
                    raise RuntimeError("Unexpected UE")
                if (g["rb_size"] <= 0 or g["rb_start"] < 0
                        or g["rb_start"] + g["rb_size"] > g["bwp_size"]
                        or g["tb_bytes"] <= 0):
                    raise RuntimeError("Invalid actual grant")
                actual[s] += g["rb_size"]
                totals[s] += g["rb_size"]
            caps = [policy["available"] * q // 100 for q in quotas]
            if policy["caps"] != caps or actual != policy["used"]:
                raise RuntimeError("Actual grants differ from policy")
            if any(u > c for u, c in zip(actual, caps)):
                raise RuntimeError("Slice cap exceeded")
            ordered = sorted(items, key=lambda g: g["bwp_start"] + g["rb_start"])
            for a, b in zip(ordered, ordered[1:]):
                if (a["bwp_start"] + a["rb_start"] + a["rb_size"]
                        > b["bwp_start"] + b["rb_start"]):
                    raise RuntimeError("Overlapping actual grants")
        if any((total != 0 if q == 0 else total <= 0)
               for q, total in zip(quotas, totals)):
            raise RuntimeError("Unexpected slice service")
        summary.update(passed=True, total_prb=totals,
                       policy_slots=len(policies), actual_grants_verified=True)
    except subprocess.TimeoutExpired as error:
        def decode(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        (output / "scheduler.log").write_text(
            decode(error.stdout) + decode(error.stderr))
        summary["error"] = "Scheduler timeout"
        raise
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print("E2_PRB_EXECUTION " + json.dumps(
            {**summary, "evidence": str(output)}), flush=True)

if __name__ == "__main__":
    main()
