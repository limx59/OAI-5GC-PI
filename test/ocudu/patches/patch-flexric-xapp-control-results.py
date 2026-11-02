#!/usr/bin/env python3
"""Handle correlated control ACK/Failure in an isolated build copy."""
import argparse
from pathlib import Path
import re

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)

def edit(text, name, change):
    pattern = (r"(?m)^[ \t]*[A-Za-z_]\w*[ \t*]+" + re.escape(name)
               + r"\s*\([^;{}]*\)\s*\{")
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise RuntimeError("Unexpected function: " + name)
    match = matches[0]
    end = text.find("\n}", match.end())
    if end < 0:
        raise RuntimeError("Missing function end: " + name)
    end += 2
    return text[:match.start()] + change(text[match.start():end]) + text[end:]

def transform(root):
    handler = "src/xApp/msg_handler_xapp.c"
    sender = "src/xApp/e42_xapp.c"
    h = (root / handler).read_text()
    s = (root / sender).read_text()
    if "set_act_proc_control_outcome" not in (root / "src/xApp/act_proc.h").read_text():
        raise RuntimeError("Apply control outcome prerequisite first")
    if "LAB_RC_FAILURE_XAPP" in h:
        raise RuntimeError("Control result handlers already present")

    h = edit(h, "e2ap_handle_control_ack_xapp", lambda section: once(
        section,
        "  act_proc_ans_t rv = find_act_proc(&xapp->act_proc, ack->ric_id.ric_req_id);",
        """  if (!set_act_proc_control_outcome(&xapp->act_proc, ack->ric_id, 1)) {
    fprintf(stderr, "LAB_RC_IGNORED_ACK request=%u\\n",
            (unsigned)ack->ric_id.ric_req_id);
    e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};
    return none;
  }
  act_proc_ans_t rv = find_act_proc(&xapp->act_proc, ack->ric_id.ric_req_id);""",
    ))

    def failure(section):
        return section[:section.index("{") + 1] + """
  assert(xapp != NULL);
  assert(msg != NULL);
  assert(msg->type == RIC_CONTROL_FAILURE);
  ric_control_failure_t const* failure = &msg->u_msgs.ric_ctrl_fail;
  e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};
  if (!set_act_proc_control_outcome(&xapp->act_proc, failure->ric_id, 2)) {
    fprintf(stderr, "LAB_RC_IGNORED_FAILURE request=%u\\n",
            (unsigned)failure->ric_id.ric_req_id);
    return none;
  }
  act_proc_ans_t active =
      find_act_proc(&xapp->act_proc, failure->ric_id.ric_req_id);
  assert(active.ok);
  pending_event_xapp_t ev = {
      .ev = E42_RIC_CONTROL_REQUEST_PENDING_EVENT, .id = active.val.id};
  rm_pending_event_xapp(xapp, &ev);
  printf("LAB_RC_FAILURE_XAPP request=%u instance=%u function=%u\\n",
         (unsigned)failure->ric_id.ric_req_id,
         (unsigned)failure->ric_id.ric_inst_id,
         (unsigned)failure->ric_id.ran_func_id);
  fflush(stdout);
  signal_sync_ui(&xapp->sync);
  return none;
}"""
    h = edit(h, "e2ap_handle_control_failure_xapp", failure)
    s = edit(s, "control_sm_sync_xapp", lambda section: once(
        section,
        "  // Answer received",
        """  act_proc_ans_t outcome =
      find_act_proc(&xapp->act_proc, ric_id.ric_req_id);
  if (!outcome.ok || outcome.val.control_outcome != 1) {
    if (outcome.ok) {
      rm_act_proc(&xapp->act_proc, ric_id.ric_req_id);
    }
    sm_ans_xapp_t rejected = {0};
    rejected.success = false;
    rejected.u.reason = "Control ACK not validated";
    return rejected;
  }

  // Answer received""",
    ))
    return {handler: h, sender: s}

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
