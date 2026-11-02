#!/usr/bin/env python3
"""Forward control failures through an isolated laboratory RIC."""
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
        raise RuntimeError("Missing function end")
    end += 2
    return text[:match.start()] + change(text[match.start():end]) + text[end:]

def transform(root):
    names = (
        "src/ric/msg_handler_ric.c",
        "src/ric/iApp/e42_iapp.c",
        "src/ric/iApp/msg_handler_iapp.c",
    )
    texts = {name: (root / name).read_text() for name in names}
    if "try_find_map_xapps_sad" not in (
        root / "src/ric/iApp/map_xapps_sockaddr.h"
    ).read_text():
        raise RuntimeError("Apply RIC disconnect prerequisite first")
    if "forward_control_failure_iapp" in texts[names[2]]:
        raise RuntimeError("Control failure forwarding already present")

    def failure(section):
        return section[:section.index("{") + 1] + """
  assert(ric != NULL);
  assert(msg != NULL);
  assert(msg->type == RIC_CONTROL_FAILURE);
  ric_gen_id_t id = msg->u_msgs.ric_ctrl_fail.ric_id;
  pending_event_ric_t ev = {
      .ev = CONTROL_REQUEST_PENDING_EVENT, .id = id};
  stop_pending_event(ric, &ev);
  printf("LAB_RC_FAILURE_RIC request=%u instance=%u function=%u\\n",
         (unsigned)id.ric_req_id, (unsigned)id.ric_inst_id,
         (unsigned)id.ran_func_id);
  fflush(stdout);
#ifndef TEST_AGENT_RIC
  notify_msg_iapp_api(msg);
#endif
  e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};
  return none;
}"""
    texts[names[0]] = edit(
        texts[names[0]], "e2ap_handle_control_failure_ric", failure)
    texts[names[1]] = once(
        texts[names[1]],
        "      || msg->type == RIC_CONTROL_ACKNOWLEDGE",
        "      || msg->type == RIC_CONTROL_ACKNOWLEDGE\n"
        "      || msg->type == RIC_CONTROL_FAILURE",
    )
    texts[names[2]] = once(
        texts[names[2]],
        "      || msg_type == RIC_CONTROL_ACKNOWLEDGE",
        "      || msg_type == RIC_CONTROL_ACKNOWLEDGE\n"
        "      || msg_type == RIC_CONTROL_FAILURE",
    )
    implementation = r"""
static e2ap_msg_t forward_control_failure_iapp(
    e42_iapp_t* iapp, const e2ap_msg_t* msg)
{
  assert(iapp != NULL);
  assert(msg != NULL);
  assert(msg->type == RIC_CONTROL_FAILURE);
  ric_gen_id_t id = msg->u_msgs.ric_ctrl_fail.ric_id;
  xapp_ric_id_xpct_t found =
      find_xapp_map_ric_id(&iapp->map_ric_id, id.ric_req_id);
  e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};
  if (!found.has_value) {
    fprintf(stderr, "LAB_RC_UNMAPPED_FAILURE request=%u\n",
            (unsigned)id.ric_req_id);
    return none;
  }
  xapp_ric_id_t x = found.xapp_ric_id;
  if (id.ran_func_id != x.ric_id.ran_func_id ||
      id.ric_inst_id != x.ric_id.ric_inst_id) {
    fprintf(stderr, "LAB_RC_FAILURE_IDENTITY_MISMATCH\n");
    return none;
  }
  sctp_msg_t wire = {0};
  if (!try_find_map_xapps_sad(&iapp->ep.xapps, x.xapp_id, &wire.info)) {
    rm_map_ric_id(&iapp->map_ric_id, &x);
    return none;
  }
  // Borrow original diagnostic pointers during synchronous encoding only.
  e2ap_msg_t forwarded = *msg;
  forwarded.u_msgs.ric_ctrl_fail.ric_id = x.ric_id;
  wire.ba = e2ap_msg_enc_iapp(&iapp->ap, &forwarded);
  defer({ free_sctp_msg(&wire); });
  e2ap_send_sctp_msg_iapp(&iapp->ep, &wire);
  printf("LAB_RC_FAILURE_FORWARD xapp=%u ric_request=%u xapp_request=%u instance=%u function=%u\n",
         (unsigned)x.xapp_id, (unsigned)id.ric_req_id,
         (unsigned)x.ric_id.ric_req_id, (unsigned)x.ric_id.ric_inst_id,
         (unsigned)x.ric_id.ran_func_id);
  fflush(stdout);
  rm_map_ric_id(&iapp->map_ric_id, &x);
  return none;
}

"""
    texts[names[2]] = once(
        texts[names[2]], "void init_handle_msg_iapp(",
        implementation + "void init_handle_msg_iapp(")
    texts[names[2]] = once(
        texts[names[2]],
        "  (*handle_msg)[RIC_CONTROL_ACKNOWLEDGE] = e2ap_handle_e42_ric_control_ack_iapp;",
        "  (*handle_msg)[RIC_CONTROL_ACKNOWLEDGE] = e2ap_handle_e42_ric_control_ack_iapp;\n"
        "  (*handle_msg)[RIC_CONTROL_FAILURE] = forward_control_failure_iapp;",
    )
    return texts

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
