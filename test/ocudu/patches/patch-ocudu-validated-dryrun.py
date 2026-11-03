#!/usr/bin/env python3
"""Run existing gNB configuration validation before dry-run exit."""
import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected source anchor: " + old[:100])
    return text.replace(old, new, 1)


def transform(root):
    root = root.resolve()
    name = "apps/gnb/gnb.cpp"
    path = root / name
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise RuntimeError("Missing or unexpected gNB source")
    text = path.read_text()
    text = once(
        text,
        "  // Dry run mode, exit.\n"
        "  if (gnb_cfg.enable_dryrun) {\n"
        "    return 0;\n"
        "  }\n",
        "",
    )
    anchor = '    report_error("Invalid configuration detected.\\n");\n  }\n'
    text = once(
        text, anchor,
        anchor
        + "\n  // Laboratory configuration checker: exit before initialization.\n"
        + "  if (gnb_cfg.enable_dryrun) {\n"
        + '    fmt::println("LAB_CONFIG_VALIDATION_PASSED");\n'
        + "    return 0;\n"
        + "  }\n",
    )
    if not (
        text.index("!o_du_app_unit->on_configuration_validation()")
        < text.index("LAB_CONFIG_VALIDATION_PASSED")
        < text.index("  // Set up logging.")
    ):
        raise RuntimeError("Unexpected validation/initialization order")
    return {name: text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise RuntimeError("Refusing to modify a Git working tree")
    files = transform(root)
    for name, text in files.items():
        if not args.check:
            (root / name).write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ") + name)


if __name__ == "__main__":
    main()
