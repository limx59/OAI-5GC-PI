#!/usr/bin/env python3
"""Preserve request identity in OCUDU subscription delete failures."""

import argparse
from pathlib import Path


def transform(root):
    name = "lib/e2/common/e2_subscription_manager_impl.cpp"
    text = (root / name).read_text()
    marker = "// Preserve correlation fields for unsuccessful outcomes."
    if marker in text:
        raise SystemExit("STOP: identity patch already present")

    old = "  outcome.response->ric_request_id             = msg->ric_request_id;\n"
    if text.count(old) != 1:
        raise SystemExit("STOP: unexpected delete-response identity anchor")
    new = old + (
        "  " + marker + "\n"
        "  outcome.failure->ran_function_id = msg->ran_function_id;\n"
        "  outcome.failure->ric_request_id = msg->ric_request_id;\n"
    )
    return name, text.replace(old, new, 1)


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
    name, updated = transform(root)
    if not args.check:
        (root / name).write_text(updated)
    print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("Identity fields only; compilation and behavior tests pending.")


if __name__ == "__main__":
    main()
