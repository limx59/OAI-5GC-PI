#!/usr/bin/env python3
"""Patch the Docker source copy to preserve optional scalar CU/DU IDs."""

import argparse
from pathlib import Path

def patched_text(text):
    for access, target, expected in (
        ("src->id.cu_du_id", "tmp.id", 1),
        ("e2_node->cu_du_id", "ind.id", 5),
        ("e2_node->cu_du_id", "swig_data.id", 1),
    ):
        old = f"""  size_t cuduid_idx = 0;
  if ({access}) {{
    while ({access}[cuduid_idx]) {{
      {target}.cu_du_id.push_back({access}[cuduid_idx]);
      cuduid_idx++;
    }}
  }}"""
        new = f"""  if ({access} != nullptr) {{
    {target}.cu_du_id.push_back(*{access});
  }}"""
        if target == "tmp.id":
            old = "\n".join("  " + line for line in old.split("\n"))
            new = "\n".join("  " + line for line in new.split("\n"))
        if text.count(old) != expected:
            raise SystemExit(
                f"STOP: expected {expected} scalar-copy anchors for {target}"
            )
        text = text.replace(old, new)

    old = """  global_e2_node_id_t* e2node_id = (global_e2_node_id_t*)id;
  sm_ans_xapp_t ans = report_sm_xapp_api(e2node_id, SM_KPM_ID, &kpm_sub, sm_cb_kpm);"""
    new = """  assert(id->cu_du_id.size() <= 1);
  uint64_t cu_du_id_value = 0;
  global_e2_node_id_t e2node_id = {};
  e2node_id.type = id->type;
  e2node_id.plmn = id->plmn;
  e2node_id.nb_id = id->nb_id;
  if (!id->cu_du_id.empty()) {
    cu_du_id_value = id->cu_du_id.front();
    e2node_id.cu_du_id = &cu_du_id_value;
  }
  sm_ans_xapp_t ans = report_sm_xapp_api(&e2node_id, SM_KPM_ID, &kpm_sub, sm_cb_kpm);"""
    if text.count(old) != 1:
        raise SystemExit("STOP: expected exactly one KPM conversion anchor.")
    return text.replace(old, new, 1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="Validate anchors without writing changes.")
    args = parser.parse_args()
    source = args.source_root / "src/xApp/swig/swig_wrapper.cpp"
    result = patched_text(source.read_text())
    if args.check:
        print("PASS: all patch anchors matched; no source changes written.")
    else:
        source.write_text(result)
        print("Applied: scalar CU/DU ID copies and explicit KPM conversion.")

if __name__ == "__main__":
    main()
