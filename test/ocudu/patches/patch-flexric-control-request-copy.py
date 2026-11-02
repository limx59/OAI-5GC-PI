#!/usr/bin/env python3
"""Preserve the xApp request identity while forwarding in a build copy."""
import argparse
from pathlib import Path

def transform(root):
    name = "src/ric/near_ric.c"
    text = (root / name).read_text()
    start = text.index("uint16_t fwd_ric_control_request(")
    end = text.index("\n}", start) + 2
    section = text[start:end]
    old = """  uint16_t const ric_req_id = ric->req_id++;
  *(uint16_t*)&cr->ric_id.ric_req_id = ric_req_id;"""
    new = """  // Borrow payload pointers for synchronous encoding only.
  // Preserve the caller's xApp-side request identity.
  ric_control_request_t forwarded_control = *cr;
  cr = &forwarded_control;
  uint16_t const ric_req_id = ric->req_id++;
  forwarded_control.ric_id.ric_req_id = ric_req_id;"""
    if section.count(old) != 1:
        raise RuntimeError("Unexpected control forwarding anchor")
    section = section.replace(old, new, 1)
    return {name: text[:start] + section + text[end:]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only to an isolated build copy")
    for name, text in transform(root).items():
        if not args.check:
            (root / name).write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ") + name)

if __name__ == "__main__":
    main()
