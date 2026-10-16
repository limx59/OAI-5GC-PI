#!/usr/bin/env python3
"""Handle missing xApp connections in the Docker RIC source copy."""

import argparse
from pathlib import Path


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: expected exactly one anchor: {label}")
    return text.replace(old, new, 1)


def patched_sources(root):
    directory = root / "src/ric/iApp"
    sources = {
        name: (directory / name).read_text()
        for name in (
            "map_xapps_sockaddr.h",
            "map_xapps_sockaddr.c",
            "msg_handler_iapp.c",
            "endpoint_iapp.c",
        )
    }

    declaration = (
        "sctp_info_t find_map_xapps_sad(map_xapps_sockaddr_t* m, "
        "uint16_t xapp_id);"
    )
    sources["map_xapps_sockaddr.h"] = replace_once(
        sources["map_xapps_sockaddr.h"],
        declaration,
        "bool try_find_map_xapps_sad(map_xapps_sockaddr_t* m,\n"
        "                            uint16_t xapp_id, sctp_info_t* out);\n\n"
        + declaration,
        "optional lookup declaration",
    )

    anchor = (
        "sctp_info_t find_map_xapps_sad(map_xapps_sockaddr_t* m, "
        "uint16_t xapp_id)\n"
    )
    implementation = """bool try_find_map_xapps_sad(map_xapps_sockaddr_t* m,
                            uint16_t xapp_id, sctp_info_t* out)
{
  assert(m != NULL);
  assert(out != NULL);

  int rc = pthread_rwlock_rdlock(&m->rw);
  assert(rc == 0);

  assoc_rb_tree_t* tree = &m->bimap.left;
  void* it = assoc_front(tree);
  void* end = assoc_end(tree);
  it = find_if(tree, it, end, &xapp_id, eq_uint16_wrapper);

  bool const found = it != end;
  if (found)
    *out = *(sctp_info_t*)assoc_value(tree, it);

  rc = pthread_rwlock_unlock(&m->rw);
  assert(rc == 0);
  return found;
}

"""
    sources["map_xapps_sockaddr.c"] = replace_once(
        sources["map_xapps_sockaddr.c"],
        anchor,
        implementation + anchor,
        "optional lookup implementation",
    )

    text = sources["msg_handler_iapp.c"]
    handlers = (
        ("e2ap_handle_subscription_response_iapp", False),
        ("e2ap_handle_subscription_delete_response_iapp", True),
        ("e2ap_handle_e42_ric_control_ack_iapp", True),
        ("e2ap_handle_ric_indication_iapp", False),
    )
    old = "  sctp_msg.info = find_map_xapps_sad(&iapp->ep.xapps, x.xapp_id);"

    for name, remove_mapping in handlers:
        start_marker = f"e2ap_msg_t {name}("
        if text.count(start_marker) != 1:
            raise SystemExit(f"STOP: unexpected handler: {name}")
        start = text.index(start_marker)
        end = text.index("\n}\n", start) + len("\n}\n")
        body = text[start:end]
        cleanup = (
            "    rm_map_ric_id(&iapp->map_ric_id, &x);\n"
            if remove_mapping else ""
        )
        new = (
            "  if (!try_find_map_xapps_sad(&iapp->ep.xapps,\n"
            "                              x.xapp_id, &sctp_msg.info)) {\n"
            f'    printf("[iApp]: {name}: xApp %u disconnected; '
            'skip forwarding\\n", (unsigned)x.xapp_id);\n'
            + cleanup
            + "    e2ap_msg_t none = {.type = NONE_E2_MSG_TYPE};\n"
              "    return none;\n"
              "  }"
        )
        updated = replace_once(body, old, new, name)
        text = text[:start] + updated + text[end:]

    sources["msg_handler_iapp.c"] = text

    old = (
        "  msg.info = find_map_xapps_sad("
        "(map_xapps_sockaddr_t*)&ep->xapps, xapp_id);"
    )
    new = """  if (!try_find_map_xapps_sad((map_xapps_sockaddr_t*)&ep->xapps,
                              xapp_id, &msg.info)) {
    printf("[iApp]: xApp %d disconnected; skip byte forwarding\\n", xapp_id);
    return;
  }"""
    sources["endpoint_iapp.c"] = replace_once(
        sources["endpoint_iapp.c"], old, new, "byte forwarding"
    )
    return {directory / name: text for name, text in sources.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    updates = patched_sources(args.source_root)
    if args.check:
        print("PASS: all disconnect patch anchors matched; no source changes.")
        return
    for path, text in updates.items():
        path.write_text(text)
        print(f"Patched: {path}")


if __name__ == "__main__":
    main()
