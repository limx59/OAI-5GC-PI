#!/usr/bin/env python3
"""Store correlated control outcomes in an isolated build copy."""
import argparse
from pathlib import Path

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)

def transform(root):
    header = "src/xApp/act_proc.h"
    source = "src/xApp/act_proc.c"
    h = (root / header).read_text()
    c = (root / source).read_text()
    if "set_act_proc_control_outcome" in h + c:
        raise RuntimeError("Control outcome patch already present")

    h = once(h, "  act_proc_val_e type;", """  act_proc_val_e type;
  // Zero-initialized by the existing designated initializer.
  // 0: pending, 1: correlated ACK, 2: correlated Failure.
  unsigned control_outcome;""")
    h = once(
        h,
        "act_proc_ans_t find_act_proc(act_proc_t* proc, uint16_t ric_req_id);",
        """act_proc_ans_t find_act_proc(act_proc_t* proc, uint16_t ric_req_id);

// Update only an existing, matching, pending control procedure.
bool set_act_proc_control_outcome(act_proc_t* proc, ric_gen_id_t id,
                                  unsigned outcome);""",
    )
    c += """
bool set_act_proc_control_outcome(act_proc_t* proc, ric_gen_id_t id,
                                  unsigned outcome)
{
  assert(proc != NULL);
  assert(outcome == 1 || outcome == 2);
  lock_guard(&proc->mtx);
  void* end = assoc_reg_end(&proc->reg);
  void* it = find_reg(&proc->reg, assoc_reg_front(&proc->reg),
                      end, id.ric_req_id);
  if (it == end) {
    return false;
  }
  act_proc_val_t* value = (act_proc_val_t*)assoc_reg_value(&proc->reg, it);
  if (value->type != RIC_CONTROL_PROCEDURE_ACTIVE ||
      value->id.ran_func_id != id.ran_func_id ||
      value->id.ric_inst_id != id.ric_inst_id ||
      value->control_outcome != 0) {
    return false;
  }
  value->control_outcome = outcome;
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
        raise SystemExit("STOP: apply only to an isolated build copy")
    updates = transform(root)
    for name, text in updates.items():
        if not args.check:
            (root / name).write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ") + name)

if __name__ == "__main__":
    main()
