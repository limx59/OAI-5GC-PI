#!/usr/bin/env python3
"""Wire the existing optional monotonic KPM report clock to CU-UP E2."""

import argparse
from pathlib import Path
import re


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def regex_once(text, pattern, replacement):
    if len(list(re.finditer(pattern, text))) != 1:
        raise SystemExit(f"STOP: unexpected pattern: {pattern!r}")
    return re.sub(pattern, replacement, text, count=1)


def add_member(text, structure, declaration):
    pattern = r"\bstruct\s+" + re.escape(structure) + r"\s*\{"
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise SystemExit(f"STOP: unexpected structure: {structure}")
    end = text.index("\n};", matches[0].end())
    return text[:end] + "\n" + declaration + "\n" + text[end:]


def transform(root):
    names = (
        "apps/gnb/gnb.cpp",
        "apps/units/o_cu_up/o_cu_up_unit_dependencies.h",
        "apps/units/o_cu_up/o_cu_up_builder.cpp",
        "include/ocudu/cu_up/o_cu_up_config.h",
        "lib/cu_up/o_cu_up_factory.cpp",
        "include/ocudu/e2/e2_cu_up_factory.h",
        "lib/e2/common/e2_cu_up_factory.cpp",
    )
    texts = {name: (root / name).read_text() for name in names}
    marker = "kpm_report_timer_manager"
    if any(marker in text for text in texts.values()):
        raise SystemExit("STOP: CU-UP report clock wiring already present")
    if "kpm_wall_source" not in texts[names[0]]:
        raise SystemExit("STOP: apply the existing DU wall-clock patch first")
    dependency_header = root / "include/ocudu/e2/e2_agent_dependencies.h"
    if "kpm_report_timers" not in dependency_header.read_text():
        raise SystemExit("STOP: apply the common KPM clock dependency patch first")

    # The application owns the timer manager and its IO source.
    texts[names[0]] = once(
        texts[names[0]],
        "  // Create O-CU-UP.\n",
        "  // Optional report clock only; CU-UP protocol timers stay unchanged.\n"
        "  o_cuup_unit_deps.kpm_report_timer_manager =\n"
        "      kpm_wall_source.has_value() ? &kpm_wall_timers : nullptr;\n\n"
        "  // Create O-CU-UP.\n",
    )

    declaration = (
        "  /// Optional KPM reporting clock owned by the application.\n"
        "  timer_manager* kpm_report_timer_manager = nullptr;"
    )
    texts[names[1]] = add_member(
        texts[names[1]], "o_cu_up_unit_dependencies", declaration,
    )
    texts[names[3]] = add_member(
        texts[names[3]], "o_cu_up_dependencies", declaration,
    )

    texts[names[2]] = regex_once(
        texts[names[2]],
        r"(\.e2_client\s*=\s*e2_client)\};",
        r"\1,\n"
        "       .kpm_report_timer_manager = dependencies.kpm_report_timer_manager};",
    )

    texts[names[4]] = once(
        texts[names[4]],
        "      std::move(collector));",
        "      std::move(collector),\n"
        "      dependencies.kpm_report_timer_manager);",
    )

    # Preserve existing callers through a default null optional clock.
    texts[names[5]] = once(
        texts[names[5]],
        "node_component_config_provider_);",
        "node_component_config_provider_,\n"
        "                       timer_manager* kpm_report_timer_manager_ = nullptr);",
    )
    texts[names[6]] = once(
        texts[names[6]],
        "node_component_config_provider_)\n",
        "node_component_config_provider_,\n"
        "                              timer_manager* kpm_report_timer_manager_)\n",
    )
    texts[names[6]] = once(
        texts[names[6]],
        "  // E2SM-KPM\n",
        "  if (kpm_report_timer_manager_ != nullptr) {\n"
        "    dependencies.kpm_report_timers.emplace(*kpm_report_timer_manager_, e2_exec_);\n"
        '    logger.info("Experimental monotonic CU-UP KPM reporting clock enabled");\n'
        "  }\n\n"
        "  // E2SM-KPM\n",
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
        raise SystemExit("STOP: apply only to an isolated source copy outside Git")
    texts = transform(root)
    for name, text in texts.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCHED'}: {name}")
    print("CU-UP KPM report scheduling only; PDCP collection clock unchanged.")
    print("Compilation, timer-selection tests and live validation pending.")


if __name__ == "__main__":
    main()
