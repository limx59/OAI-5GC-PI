#!/usr/bin/env python3
"""Handle Agent epoll interruption only in the dedicated image source copy."""

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply-qos-fault.py /src/flexric")
root = Path(sys.argv[1]).resolve()
if root != Path("/src/flexric") or not root.is_dir():
    raise SystemExit("Only the container source copy /src/flexric is allowed.")

p = root / "src/agent/asio_agent.c"
text = p.read_text(encoding="utf-8")
old = "  if (events_ready < 0) {"
new = """  if (events_ready < 0 && errno == EINTR)
    return -1; // Resume the Agent loop after pause/unpause interrupts epoll.
  if (events_ready < 0) {"""
if text.count(old) != 1:
    raise SystemExit("Unexpected epoll error block; no changes saved.")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Applied: Agent epoll EINTR handling")
