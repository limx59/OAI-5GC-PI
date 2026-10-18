#!/usr/bin/env python3
"""Add an optional KPM report timer dependency in an isolated source copy."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def add_field(text, structure):
    anchor = "struct " + structure + " {"
    if text.count(anchor) != 1:
        raise SystemExit(f"STOP: unexpected structure: {structure}")
    start = text.index(anchor)
    end = text.index("\n};", start)
    return (
        text[:end]
        + "\n  /// Optional independent timer factory for KPM reporting.\n"
        + "  std::optional<timer_factory> kpm_report_timers = std::nullopt;\n"
        + text[end:]
    )


def transform(root):
    names = [
        "include/ocudu/e2/e2ap_config.h",
        "include/ocudu/e2/e2_agent_dependencies.h",
        "lib/e2/common/e2_du_factory.cpp",
        "lib/e2/common/e2_entity.cpp",
        "lib/e2/common/e2_impl.h",
    ]
    texts = {name: (root / name).read_text() for name in names}
    if any("kpm_report_timers" in text for text in texts.values()):
        raise SystemExit("STOP: clock dependency already present")

    for name, structure in [
        (names[0], "e2ap_dependencies"),
        (names[1], "e2_agent_dependencies"),
        (names[4], "e2_impl_dependencies"),
    ]:
        text = texts[name]
        if "#include <optional>" not in text:
            text = once(text, "\nnamespace ocudu {",
                        "\n#include <optional>\n\nnamespace ocudu {")
        texts[name] = add_field(text, structure)

    texts[names[2]] = once(
        texts[names[2]],
        ".e2sm_modules = {}};",
        ".e2sm_modules = {},\n"
        "                                           .kpm_report_timers = dependencies.kpm_report_timers};",
    )
    texts[names[3]] = once(
        texts[names[3]],
        ".task_exec         = dependencies.task_exec});",
        ".task_exec         = dependencies.task_exec,\n"
        "                                                        .kpm_report_timers = dependencies.kpm_report_timers});",
    )
    return texts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    texts = transform(root)

    if not args.check:
        if any((p / ".git").exists() for p in (root, *root.parents)):
            raise SystemExit("STOP: apply only to an isolated source copy outside Git.")
        for name, text in texts.items():
            (root / name).write_text(text)

    for name in texts:
        print(f"{'CHECK' if args.check else 'PATCHED'}: {name}")
    print("Dependency plumbing only; existing timer selection unchanged.")


if __name__ == "__main__":
    main()
