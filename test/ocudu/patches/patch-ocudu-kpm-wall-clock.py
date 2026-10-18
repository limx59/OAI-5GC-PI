#!/usr/bin/env python3
"""Wire an opt-in monotonic timer source to DU KPM reporting."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    names = [
        "apps/gnb/gnb.cpp",
        "apps/units/flexible_o_du/o_du_unit.h",
        "apps/units/flexible_o_du/split_helpers/flexible_o_du_factory.cpp",
        "include/ocudu/du/du_high/o_du_high_config.h",
        "lib/du/du_high/o_du_high_factory.cpp",
    ]
    texts = {name: (root / name).read_text() for name in names}
    if any("kpm_wall_timers" in text for text in texts.values()):
        raise SystemExit("STOP: wall clock wiring already present")

    name = names[0]
    text = once(
        texts[name], "\nusing namespace ocudu;",
        '\n#include "ocudu/support/io/io_timer_source.h"\n'
        '#include <cstdlib>\n\nusing namespace ocudu;',
    )
    anchor = (
        "  auto time_ctrl = odu::create_du_high_clock_controller("
        "app_timers, *epoll_broker, workers.get_timer_source_executor());"
    )
    addition = (
        "\n\n  // Experimental reporting clock independent of DU cell timing.\n"
        "  timer_manager kpm_wall_timers{64};\n"
        "  std::optional<io_timer_source> kpm_wall_source;\n"
        '  const char* kpm_clock_option = std::getenv("OCUDU_KPM_WALL_CLOCK");\n'
        '  if (kpm_clock_option != nullptr && std::string(kpm_clock_option) == "1") {\n'
        "    kpm_wall_source.emplace(kpm_wall_timers,\n"
        "                            *epoll_broker,\n"
        "                            workers.get_timer_source_executor(),\n"
        "                            std::chrono::milliseconds{1});\n"
        '    gnb_logger.info("Experimental monotonic KPM reporting clock enabled");\n'
        "  }\n"
    )
    text = once(text, anchor, anchor + addition)
    text = once(
        text, "  o_du_unit_dependencies odu_dependencies;\n",
        "  o_du_unit_dependencies odu_dependencies;\n"
        "  odu_dependencies.kpm_wall_timers = kpm_wall_source.has_value() ? &kpm_wall_timers : nullptr;\n",
    )
    text = once(
        text, "  // Stop O-CU-UP activity.\n",
        "  // Stop the report clock while its executor and IO broker are still alive.\n"
        "  kpm_wall_source.reset();\n\n"
        "  // Stop O-CU-UP activity.\n",
    )
    texts[name] = text

    for name, structure in (
        (names[1], "o_du_unit_dependencies"),
        (names[3], "o_du_high_dependencies"),
    ):
        text = texts[name]
        anchor = "struct " + structure + " {"
        if text.count(anchor) != 1:
            raise SystemExit(f"STOP: unexpected structure: {structure}")
        end = text.index("\n};", text.index(anchor))
        texts[name] = (
            text[:end]
            + "\n  /// Optional timer manager owned by the application.\n"
            + "  timer_manager* kpm_wall_timers = nullptr;\n"
            + text[end:]
        )

    name = names[2]
    anchor = "  // Bridge the NTN configuration manager"
    texts[name] = once(
        texts[name], anchor,
        "  odu_hi_unit_dependencies.o_du_hi_dependencies.kpm_wall_timers = dependencies.kpm_wall_timers;\n\n"
        + anchor,
    )

    name = names[4]
    text = once(
        texts[name], "  auto e2agent = create_e2_du_agent(\n",
        "  std::optional<timer_factory> report_timers;\n"
        "  if (odu_dependencies.kpm_wall_timers != nullptr) {\n"
        "    report_timers.emplace(*odu_dependencies.kpm_wall_timers,\n"
        "                          odu_dependencies.du_hi.exec_mapper->du_e2_executor());\n"
        "  }\n\n"
        "  auto e2agent = create_e2_du_agent(\n",
    )
    text = once(
        text,
        '.logger                         = ocudulog::fetch_basic_logger("E2-DU")});',
        '.logger                         = ocudulog::fetch_basic_logger("E2-DU"),\n'
        '                        .kpm_report_timers = report_timers});',
    )
    texts[name] = text
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
    print("Opt-in scheduling only; freshness and runtime acceptance pending.")


if __name__ == "__main__":
    main()
