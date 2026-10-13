#!/usr/bin/env python3
"""Use controlled MAC load reports only in the dedicated emulator build."""

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply-steering-load.py /src/flexric")
root = Path(sys.argv[1]).resolve()
if root != Path("/src/flexric") or not root.is_dir():
    raise SystemExit("Only the container source copy /src/flexric is allowed.")

helper = Path("/src/test/flexric/native/steering_mac_report.h")
if not helper.is_file():
    raise SystemExit("Controlled MAC report helper missing.")

p = root / "examples/emulator/agent/sm_mac.c"
text = p.read_text(encoding="utf-8")
changes = (
    (
        '#include "sm_mac.h"',
        '#include "sm_mac.h"\n'
        '#include "/src/test/flexric/native/steering_mac_report.h"',
    ),
    (
        "  fill_mac_ind_data(mac);",
        "  steering_fill_mac_report(mac);",
    ),
)
for old, new in changes:
    if text.count(old) != 1:
        raise SystemExit(f"Source mismatch: sm_mac.c: {old!r}; no changes saved.")
    text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")
print("Applied: controlled emulator MAC load reports")
