#!/usr/bin/env python3
"""Inject one explicitly enabled delete rejection in a test source copy."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    source = "lib/e2/common/e2_subscription_manager_impl.cpp"
    header = "lib/e2/common/e2_subscription_manager_impl.h"
    c = (root / source).read_text()
    h = (root / header).read_text()

    if "oai_pi_test_delete_rejected" in c + h:
        raise SystemExit("STOP: injection patch already present")
    if "// Preserve correlation fields for unsuccessful outcomes." not in c:
        raise SystemExit("STOP: apply delete-failure identity patch first")

    c = once(
        c,
        '#include "e2_subscription_manager_impl.h"\n',
        '#include "e2_subscription_manager_impl.h"\n'
        '#include <cstdlib>\n#include <cstring>\n',
    )
    h = once(
        h,
        "private:\n",
        "private:\n"
        "  // Test-only: consume at most one enabled rejection per manager.\n"
        "  bool oai_pi_test_delete_rejected = false;\n",
    )

    old = (
        "  if (subscriptions.count({outcome.request_id.ric_requestor_id, "
        "outcome.request_id.ric_instance_id})) {\n"
        "    outcome.success = true;\n"
    )
    new = (
        "  if (subscriptions.count({outcome.request_id.ric_requestor_id, "
        "outcome.request_id.ric_instance_id})) {\n"
        '    const char* enabled = std::getenv("OAI_PI_TEST_REJECT_FIRST_DELETE");\n'
        '    if (!oai_pi_test_delete_rejected && enabled != nullptr &&\n'
        '        std::strcmp(enabled, "1") == 0) {\n'
        "      oai_pi_test_delete_rejected = true;\n"
        "      outcome.failure->cause.set_misc();\n"
        '      logger.warning("OAI_PI_TEST_DELETE_REJECTED requestor={} instance={} ran_function={}",\n'
        "                     msg->ric_request_id.ric_requestor_id,\n"
        "                     msg->ric_request_id.ric_instance_id,\n"
        "                     msg->ran_function_id);\n"
        "      return outcome;\n"
        "    }\n"
        "    outcome.success = true;\n"
    )
    c = once(c, old, new)
    return {source: c, header: h}


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
    updates = transform(root)
    for name, text in updates.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("Test injection only; compilation and behavior tests pending.")


if __name__ == "__main__":
    main()
