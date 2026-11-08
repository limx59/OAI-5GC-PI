#!/usr/bin/env python3
"""Set the sequential DU-low concurrency in the Docker build source copy."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("concurrency", type=int, choices=(1, 2))
args = parser.parse_args()

source = Path("/src/ocudu/apps/services/worker_manager/worker_manager.cpp")
text = source.read_text()
old = ".common_executor = {phy_exec, nof_workers_general_pool}"
if text.count(old) != 1:
    raise SystemExit("STOP: expected exactly one sequential DU-low anchor")

new = ".common_executor = {phy_exec, " + str(args.concurrency) + "U}"
source.write_text(text.replace(old, new, 1))
print(f"Diagnostic sequential DU-low max_concurrency={args.concurrency}", flush=True)
