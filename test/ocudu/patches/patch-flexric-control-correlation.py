#!/usr/bin/env python3
"""Add laboratory control request/ACK correlation in a build copy."""
import argparse
from pathlib import Path

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)

def transform(root):
    updates = {}
    replacements = {
        "src/xApp/e42_xapp.c": [
            (
                "  send_control_request(xapp, id, ric_id, ctrl_msg);",
                """  printf("LAB_RC_REQUEST node=%u request=%u instance=%u function=%u\\n",
         (unsigned)id->nb_id.nb_id, (unsigned)ric_id.ric_req_id,
         (unsigned)ric_id.ric_inst_id, (unsigned)ric_id.ran_func_id);
  fflush(stdout);
  send_control_request(xapp, id, ric_id, ctrl_msg);""",
            ),
        ],
        "src/xApp/msg_handler_xapp.c": [
            (
                '  printf("[xApp]: CONTROL ACK rx\\n");',
                """  printf("LAB_RC_ACK_XAPP request=%u instance=%u function=%u\\n",
         (unsigned)ack->ric_id.ric_req_id,
         (unsigned)ack->ric_id.ric_inst_id,
         (unsigned)ack->ric_id.ran_func_id);
  fflush(stdout);
  printf("[xApp]: CONTROL ACK rx\\n");""",
            ),
        ],
        "src/ric/msg_handler_ric.c": [
            (
                '  printf("[NEAR-RIC]: CONTROL ACKNOWLEDGE rx\\n");',
                """  printf("LAB_RC_ACK_RIC request=%u instance=%u function=%u\\n",
         (unsigned)ack->ric_id.ric_req_id,
         (unsigned)ack->ric_id.ric_inst_id,
         (unsigned)ack->ric_id.ran_func_id);
  fflush(stdout);
  printf("[NEAR-RIC]: CONTROL ACKNOWLEDGE rx\\n");""",
            ),
        ],
        "src/ric/iApp/msg_handler_iapp.c": [
            (
                '  printf("[iApp]: E42_RIC_CONTROL_REQUEST rx\\n");',
                """  printf("LAB_RC_MAP node=%u xapp=%u xapp_request=%u ric_request=%u instance=%u function=%u\\n",
         (unsigned)e42_cr->id.nb_id.nb_id,
         (unsigned)e42_cr->xapp_id,
         (unsigned)e42_cr->ctrl_req.ric_id.ric_req_id,
         (unsigned)new_ric_id,
         (unsigned)e42_cr->ctrl_req.ric_id.ric_inst_id,
         (unsigned)e42_cr->ctrl_req.ric_id.ran_func_id);
  fflush(stdout);
  printf("[iApp]: E42_RIC_CONTROL_REQUEST rx\\n");""",
            ),
            (
                '  printf("[iApp]: RIC_CONTROL_ACKNOWLEDGE tx\\n");',
                """  printf("LAB_RC_ACK_FORWARD xapp=%u ric_request=%u xapp_request=%u instance=%u function=%u\\n",
         (unsigned)x.xapp_id,
         (unsigned)src->ric_id.ric_req_id,
         (unsigned)x.ric_id.ric_req_id,
         (unsigned)x.ric_id.ric_inst_id,
         (unsigned)x.ric_id.ran_func_id);
  fflush(stdout);
  printf("[iApp]: RIC_CONTROL_ACKNOWLEDGE tx\\n");""",
            ),
        ],
    }
    for name, pairs in replacements.items():
        path = root / name
        text = path.read_text()
        if "LAB_RC_" in text:
            raise RuntimeError("Control correlation trace already present")
        for old, new in pairs:
            text = once(text, old, new)
        updates[path] = text
    return updates

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
    for path, text in updates.items():
        if not args.check:
            path.write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ")
              + str(path.relative_to(root)))

if __name__ == "__main__":
    main()
