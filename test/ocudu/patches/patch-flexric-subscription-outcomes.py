#!/usr/bin/env python3
"""Store per-request rejection outcomes in an isolated FlexRIC source copy."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    header = "src/xApp/act_proc.h"
    source = "src/xApp/act_proc.c"
    h = (root / header).read_text()
    c = (root / source).read_text()
    if "set_act_proc_rejected" in h or "set_act_proc_rejected" in c:
        raise SystemExit("STOP: outcome patch already present")

    h = once(
        h,
        "  act_proc_val_e type;",
        """  act_proc_val_e type;
  // Initialized false by the existing designated initializer.
  bool subscription_rejected;
  bool delete_rejected;""",
    )
    h = once(
        h,
        "act_proc_ans_t find_act_proc(act_proc_t* proc, uint16_t ric_req_id);",
        """act_proc_ans_t find_act_proc(act_proc_t* proc, uint16_t ric_req_id);

// Update an existing request under the registry mutex.
// False means the request is absent; never create a stale request.
bool set_act_proc_rejected(act_proc_t* proc, uint16_t ric_req_id,
                           bool deletion, bool rejected);""",
    )
    c += """
bool set_act_proc_rejected(act_proc_t* proc, uint16_t ric_req_id,
                           bool deletion, bool rejected)
{
  assert(proc != NULL);
  lock_guard(&proc->mtx);
  void* end = assoc_reg_end(&proc->reg);
  void* it = find_reg(&proc->reg, assoc_reg_front(&proc->reg),
                      end, ric_req_id);
  if (it == end) {
    return false;
  }
  act_proc_val_t* value = (act_proc_val_t*)assoc_reg_value(&proc->reg, it);
  if (deletion) {
    value->delete_rejected = rejected;
  } else {
    value->subscription_rejected = rejected;
  }
  return true;
}
"""
    return {header: h, source: c}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only outside a Git working tree")
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("Request metadata only; failure handlers and validation pending.")


if __name__ == "__main__":
    main()
