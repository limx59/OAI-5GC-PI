#!/usr/bin/env python3
"""Fix indication cancellation and header encoding order in a source copy."""

import argparse
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: expected exactly one anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(text):
    text = replace_once(
        text,
        '      logger.info("Subscription deleted");\n'
        '      running = false;\n',
        '      logger.info("Subscription deleted");\n'
        '      running = false;\n'
        '      break;\n',
    )
    text = replace_once(
        text,
        '            ind_msg_bytes = action.report_service->get_indication_message();\n'
        '            ind_hdr_bytes = action.report_service->get_indication_header();',
        '            // Preserve the current collection header before message encoding clears it.\n'
        '            ind_hdr_bytes = action.report_service->get_indication_header();\n'
        '            ind_msg_bytes = action.report_service->get_indication_message();',
    )
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    target = root / "lib/e2/procedures/e2ap_indication_procedure.cpp"
    original = target.read_text()
    updated = transform(original)

    if args.check:
        print("PASS: lifecycle anchors matched; no source changes.")
        return

    if any((directory / ".git").exists() for directory in (root, *root.parents)):
        raise SystemExit("STOP: apply only to an isolated source copy outside Git.")

    target.write_text(updated)
    print(f"Patched: {target}")


if __name__ == "__main__":
    main()
