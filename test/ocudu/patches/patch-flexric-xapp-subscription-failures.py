#!/usr/bin/env python3
"""Handle subscription rejection in an isolated FlexRIC xApp source copy."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def edit_function(text, name, transform):
    import re

    pattern = (
        r"(?m)^[ \t]*[A-Za-z_]\w*[ \t*]+"
        + re.escape(name)
        + r"\s*\([^;{}]*\)\s*\{"
    )
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise SystemExit(
            f"STOP: expected one definition of {name}, found {len(matches)}"
        )
    match = matches[0]
    start = match.start()
    end = text.find("\n}", match.end())
    if end < 0:
        raise SystemExit(f"STOP: missing closing brace: {name}")
    end += 2
    return text[:start] + transform(text[start:end]) + text[end:]


def transform(root):
    names = (
        "src/xApp/msg_handler_xapp.c",
        "src/xApp/e42_xapp.c",
        "src/xApp/swig/swig_wrapper.cpp",
    )
    texts = {name: (root / name).read_text() for name in names}
    if "set_act_proc_rejected" not in (root / "src/xApp/act_proc.h").read_text():
        raise SystemExit("STOP: apply the outcome metadata patch first")
    if "KPM_SUBSCRIPTION_REJECTED" in texts[names[0]]:
        raise SystemExit("STOP: failure patch already present")

    for deletion in (False, True):
        function = (
            "e2ap_handle_subscription_delete_failure_xapp"
            if deletion else "e2ap_handle_subscription_failure_xapp"
        )
        field = "ric_sub_del_fail" if deletion else "ric_sub_fail"
        pending = (
            "E42_RIC_SUBSCRIPTION_DELETE_REQUEST_PENDING_EVENT"
            if deletion else "E42_RIC_SUBSCRIPTION_REQUEST_PENDING_EVENT"
        )
        marker = "KPM_DELETE_REJECTED" if deletion else "KPM_SUBSCRIPTION_REJECTED"
        body = f"""  uint16_t request = msg->u_msgs.{field}.ric_id.ric_req_id;
  act_proc_ans_t active = find_act_proc(&xapp->act_proc, request);
  if (!active.ok) {{
    printf("[xApp]: Ignoring failure for absent request %u\\n", request);
    e2ap_msg_t none = {{.type = NONE_E2_MSG_TYPE}};
    return none;
  }}
  if (!set_act_proc_rejected(&xapp->act_proc, request,
                             {'true' if deletion else 'false'}, true)) {{
    e2ap_msg_t none = {{.type = NONE_E2_MSG_TYPE}};
    return none;
  }}
  pending_event_xapp_t ev = {{.ev = {pending}, .id = active.val.id}};
  rm_pending_event_xapp(xapp, &ev);
  printf("[xApp]: {marker} request=%u\\n", request);
  signal_sync_ui(&xapp->sync);"""
        texts[names[0]] = edit_function(
            texts[names[0]], function,
            lambda section, body=body: once(
                section, '  assert(0!=0 && "Not implemented");', body),
        )

    check_subscription = """
  // Inspect the request outcome after the response handler signals completion.
  act_proc_ans_t outcome = find_act_proc(&xapp->act_proc, ric_id.ric_req_id);
  if (!outcome.ok || outcome.val.subscription_rejected) {
    if (outcome.ok) {
      rm_act_proc(&xapp->act_proc, ric_id.ric_req_id);
    }
    sm_ans_xapp_t rejected = {0};
    rejected.success = false;
    rejected.u.reason = "RIC rejected subscription";
    return rejected;
  }
"""
    texts[names[1]] = edit_function(
        texts[names[1]], "report_sm_sync_xapp",
        lambda section: once(
            section,
            "  cond_wait_sync_ui(&xapp->sync, xapp->sync.wait_ms);",
            "  cond_wait_sync_ui(&xapp->sync, xapp->sync.wait_ms);\n"
            + check_subscription,
        ),
    )

    def edit_delete(section):
        section = once(
            section,
            "  // Send message\n",
            """  // Reset the previous delete outcome before submitting a retry.
  if (!set_act_proc_rejected(&xapp->act_proc, ric_req_id, true, false)) {
    return;
  }
  // Send message
""",
        )
        return once(
            section,
            "  // Remove the active procedure",
            """  act_proc_ans_t outcome = find_act_proc(&xapp->act_proc, ric_req_id);
  if (!outcome.ok || outcome.val.delete_rejected) {
    // A rejected deletion does not establish that the subscription ended.
    fprintf(stderr, "[xApp]: Delete rejected; retaining subscription %d\\n", ric_req_id);
    return;
  }

  // Remove the active procedure""",
        )
    texts[names[1]] = edit_function(
        texts[names[1]], "rm_report_sm_sync_xapp", edit_delete,
    )

    def edit_swig(section):
        section = once(
            section, "  assert(ans.success == true);",
            """  if (!ans.success) {
    fprintf(stderr, "[xApp]: KPM subscription rejected\\n");
  }""",
        )
        return once(
            section, "  return ans.u.handle;",
            "  return ans.success ? ans.u.handle : -1;",
        )
    texts[names[2]] = edit_function(
        texts[names[2]], "report_kpm_sm", edit_swig,
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
    print("xApp failure handling only; RIC/iApp forwarding and tests pending.")


if __name__ == "__main__":
    main()
