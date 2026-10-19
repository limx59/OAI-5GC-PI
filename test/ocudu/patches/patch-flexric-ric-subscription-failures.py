#!/usr/bin/env python3
"""Forward subscription failures through RIC/iApp in an isolated copy."""

import argparse
from pathlib import Path
import re


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def edit_function(text, name, change):
    pattern = (
        r"(?m)^[ \t]*[A-Za-z_]\w*[ \t*]+"
        + re.escape(name) + r"\s*\([^;{}]*\)\s*\{"
    )
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise SystemExit(f"STOP: unexpected definition: {name}")
    start = matches[0].start()
    end = text.find("\n}", matches[0].end())
    if end < 0:
        raise SystemExit(f"STOP: missing closing brace: {name}")
    end += 2
    return text[:start] + change(text[start:end]) + text[end:]


def transform(root):
    names = (
        "src/ric/msg_handler_ric.c",
        "src/ric/iApp/e42_iapp.c",
        "src/ric/iApp/msg_handler_iapp.c",
    )
    texts = {name: (root / name).read_text() for name in names}
    header = root / "src/ric/iApp/map_xapps_sockaddr.h"
    if "try_find_map_xapps_sad" not in header.read_text():
        raise SystemExit("STOP: apply the RIC disconnect patch first")
    if "forward_subscription_failure_iapp" in texts[names[2]]:
        raise SystemExit("STOP: failure forwarding already present")

    for deletion in (False, True):
        function = (
            "e2ap_handle_subscription_delete_failure_ric"
            if deletion else "e2ap_handle_subscription_failure_ric"
        )
        field = "ric_sub_del_fail" if deletion else "ric_sub_fail"
        event = (
            "SUBSCRIPTION_DELETE_REQUEST_PENDING_EVENT"
            if deletion else "SUBSCRIPTION_REQUEST_PENDING_EVENT"
        )
        body = f"""  pending_event_ric_t ev = {{
      .ev = {event}, .id = msg->u_msgs.{field}.ric_id}};
  stop_pending_event(ric, &ev);
#ifndef TEST_AGENT_RIC
  notify_msg_iapp_api(msg);
#endif"""
        texts[names[0]] = edit_function(
            texts[names[0]], function,
            lambda section, body=body: once(
                section, '  assert(0!=0 && "Not implemented");', body),
        )

    texts[names[1]] = once(
        texts[names[1]],
        "      || msg->type == RIC_SUBSCRIPTION_RESPONSE",
        """      || msg->type == RIC_SUBSCRIPTION_RESPONSE
      || msg->type == RIC_SUBSCRIPTION_FAILURE
      || msg->type == RIC_SUBSCRIPTION_DELETE_FAILURE""",
    )
    texts[names[2]] = once(
        texts[names[2]],
        "         msg_type == RIC_SUBSCRIPTION_RESPONSE",
        """         msg_type == RIC_SUBSCRIPTION_RESPONSE
      || msg_type == RIC_SUBSCRIPTION_FAILURE
      || msg_type == RIC_SUBSCRIPTION_DELETE_FAILURE""",
    )

    implementation = r"""
static e2ap_msg_t forward_subscription_failure_iapp(
    e42_iapp_t* iapp, const e2ap_msg_t* msg)
{
  assert(iapp != NULL);
  assert(msg != NULL);
  bool deletion = msg->type == RIC_SUBSCRIPTION_DELETE_FAILURE;
  assert(deletion || msg->type == RIC_SUBSCRIPTION_FAILURE);

  ric_gen_id_t source_id = deletion
      ? msg->u_msgs.ric_sub_del_fail.ric_id
      : msg->u_msgs.ric_sub_fail.ric_id;
  xapp_ric_id_xpct_t found =
      find_xapp_map_ric_id(&iapp->map_ric_id, source_id.ric_req_id);
  e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};
  if (!found.has_value) {
    printf("[iApp]: Ignoring unmapped failure request=%u\n", source_id.ric_req_id);
    return none;
  }
  xapp_ric_id_t x = found.xapp_ric_id;
  if (source_id.ran_func_id != x.ric_id.ran_func_id ||
      source_id.ric_inst_id != x.ric_id.ric_inst_id) {
    fprintf(stderr, "[iApp]: Failure request identity mismatch\n");
    return none;
  }

  sctp_msg_t wire = {0};
  if (!try_find_map_xapps_sad(&iapp->ep.xapps, x.xapp_id, &wire.info)) {
    printf("[iApp]: Failure recipient disconnected; remove mapping\n");
    rm_map_ric_id(&iapp->map_ric_id, &x);
    return none;
  }

  // Borrow diagnostic pointers only during synchronous encoding.
  // The caller retains ownership of the original message contents.
  e2ap_msg_t forwarded = *msg;
  if (deletion) {
    forwarded.u_msgs.ric_sub_del_fail.ric_id = x.ric_id;
  } else {
    forwarded.u_msgs.ric_sub_fail.ric_id = x.ric_id;
  }
  wire.ba = e2ap_msg_enc_iapp(&iapp->ap, &forwarded);
  defer({ free_sctp_msg(&wire); });
  e2ap_send_sctp_msg_iapp(&iapp->ep, &wire);
  printf("[iApp]: %s tx request=%u\n",
         deletion ? "SUBSCRIPTION_DELETE_FAILURE" : "SUBSCRIPTION_FAILURE",
         x.ric_id.ric_req_id);

  if (!deletion) {
    rm_map_ric_id(&iapp->map_ric_id, &x);
  }
  return none;
}

"""
    texts[names[2]] = once(
        texts[names[2]],
        "void init_handle_msg_iapp(",
        implementation + "void init_handle_msg_iapp(",
    )
    texts[names[2]] = once(
        texts[names[2]],
        "  (*handle_msg)[RIC_SUBSCRIPTION_RESPONSE] = e2ap_handle_subscription_response_iapp;",
        """  (*handle_msg)[RIC_SUBSCRIPTION_RESPONSE] = e2ap_handle_subscription_response_iapp;
  (*handle_msg)[RIC_SUBSCRIPTION_FAILURE] = forward_subscription_failure_iapp;
  (*handle_msg)[RIC_SUBSCRIPTION_DELETE_FAILURE] = forward_subscription_failure_iapp;""",
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
        raise SystemExit("STOP: apply only outside a Git working tree")
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("RIC/iApp forwarding only; compilation and behavior tests pending.")


if __name__ == "__main__":
    main()
