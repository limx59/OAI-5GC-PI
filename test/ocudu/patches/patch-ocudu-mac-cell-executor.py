#!/usr/bin/env python3
"""Keep MAC cell control tasks asynchronous on the shared cell strand."""
import difflib
from pathlib import Path
import sys

root = Path(sys.argv[1])
path = root / "lib/du/du_high/du_high_executor_mapper.cpp"
original = path.read_text(encoding="utf-8")
old = """      cell_strands[i].mac_cell_exec =
          &decorator.decorate(execs[0], is_sync, trace_enabled, std::nullopt, metric_channel_registry, exec_name);"""
new = """      // Cell control coroutines can already be running on the backing pool.
      // Submit without waiting for another worker from that same pool.
      cell_strands[i].mac_cell_exec =
          &decorator.decorate(execs[0], false, trace_enabled, std::nullopt, metric_channel_registry, exec_name);"""
if original.count(old) != 1:
    raise SystemExit("STOP: expected one MAC cell strand decorator")
updated = original.replace(old, new, 1)
path.write_text(updated, encoding="utf-8")
sys.stdout.writelines(difflib.unified_diff(
    original.splitlines(keepends=True),
    updated.splitlines(keepends=True),
    fromfile=str(path.relative_to(root)),
    tofile=str(path.relative_to(root)),
))
