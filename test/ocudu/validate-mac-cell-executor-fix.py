#!/usr/bin/env python3
"""Validate the OCUDU MAC cell executor fix with one and two workers."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "test/ocudu/run-phy-concurrency-diag.py"


def main():
    for workers in (1, 2):
        print(f"\n=== MAC cell executor regression: {workers} worker(s) ===", flush=True)
        status = subprocess.run(
            [sys.executable, "-B", str(RUNNER), "--main-pool-workers", str(workers)],
            cwd=ROOT,
        ).returncode
        if status:
            print(f"FAIL: {workers}-worker case exited with status {status}", file=sys.stderr)
            return status if status > 0 else 1

    print("PASS: single-worker fix and dual-worker regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
