#!/usr/bin/env python3
"""Separate optional PDCP statistics timers from protocol timers."""

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


def transform(root):
    names = (
        "include/ocudu/pdcp/pdcp_config.h",
        "apps/units/o_cu_up/o_cu_up_builder.cpp",
        "lib/pdcp/pdcp_entity_impl.h",
        "lib/pdcp/pdcp_entity_tx.h",
        "lib/pdcp/pdcp_entity_rx.h",
        "lib/pdcp/pdcp_entity_tx.cpp",
        "lib/pdcp/pdcp_entity_rx.cpp",
        "lib/pdcp/pdcp_metrics_aggregator.cpp",
    )
    texts = {name: (root / name).read_text() for name in names}
    if any("pdcp_metrics_clock_option" in text for text in texts.values()):
        raise SystemExit("STOP: PDCP metrics clock already wired")
    if "kpm_report_timer_manager" not in texts[names[1]]:
        raise SystemExit("STOP: apply CU-UP report-clock wiring first")

    texts[names[0]] = once(
        texts[names[0]],
        "struct pdcp_custom_config {\n",
        "struct pdcp_custom_config {\n"
        "  /// Optional statistics-only clock; owned by the application.\n"
        "  timer_manager* metrics_timer_manager = nullptr;\n",
    )

    text = once(
        texts[names[1]], "\nusing namespace ocudu;",
        "\n#include <cstdlib>\n#include <string>\n\nusing namespace ocudu;",
    )
    text = once(
        text,
        "  for (auto& qos_ : config.cu_up_cfg.qos) {\n",
        '  const char* pdcp_metrics_clock_option = std::getenv("OCUDU_PDCP_METRICS_WALL_CLOCK");\n'
        "  timer_manager* pdcp_metrics_clock = nullptr;\n"
        '  if (pdcp_metrics_clock_option != nullptr && std::string(pdcp_metrics_clock_option) == "1") {\n'
        "    ocudu_assert(dependencies.kpm_report_timer_manager != nullptr,\n"
        '                 "Independent PDCP metrics clock requires the application report clock");\n'
        "    pdcp_metrics_clock = dependencies.kpm_report_timer_manager;\n"
        '    ocudulog::fetch_basic_logger("CU-UP").info("Experimental monotonic PDCP metrics clock enabled");\n'
        "  }\n\n"
        "  for (auto& qos_ : config.cu_up_cfg.qos) {\n"
        "    qos_.second.pdcp_custom_cfg.metrics_timer_manager = pdcp_metrics_clock;\n",
    )
    texts[names[1]] = text

    text = once(
        texts[names[2]],
        "    tx = std::make_unique<pdcp_entity_tx>(ue_index,\n",
        "    // Preserve the control-executor serialization used by both\n"
        "    // statistics callbacks in this complete entity.\n"
        "    std::optional<timer_factory> metrics_clock;\n"
        "    if (config.custom.metrics_timer_manager != nullptr) {\n"
        "      metrics_clock.emplace(*config.custom.metrics_timer_manager, ue_ctrl_executor);\n"
        "    }\n\n"
        "    tx = std::make_unique<pdcp_entity_tx>(ue_index,\n",
    )
    pattern = r"(?m)^([ \t]*)metrics_agg\);[ \t]*$"
    if len(list(re.finditer(pattern, text))) != 2:
        raise SystemExit("STOP: expected TX and RX aggregator argument lines")
    text = re.sub(
        pattern,
        r"\1metrics_agg,\n\1metrics_clock);",
        text,
    )
    texts[names[2]] = text

    for name in names[3:5]:
        text = once(
            texts[name], "#pragma once\n",
            "#pragma once\n\n#include <optional>\n",
        )
        text = regex_once(
            text,
            r"(pdcp_metrics_aggregator&\s+metrics_agg_)\);",
            r"\1,\n"
            "                  std::optional<timer_factory> metrics_timer_factory_ = std::nullopt);",
        )
        texts[name] = text

    for name, fallback in (
        (names[5], "ue_ctrl_timer_factory"),
        (names[6], "ue_ul_timer_factory"),
    ):
        text = regex_once(
            texts[name],
            r"(pdcp_metrics_aggregator&\s+metrics_agg_)\) :",
            r"\1,\n"
            "                                std::optional<timer_factory> metrics_timer_factory_) :",
        )
        text = once(
            text,
            f"    metrics_timer = {fallback}.create_timer();",
            f"    metrics_timer = metrics_timer_factory_.value_or({fallback}).create_timer();",
        )
        texts[name] = text

    text = once(
        texts[names[7]],
        '#include "pdcp_metrics_aggregator.h"\n',
        '#include "pdcp_metrics_aggregator.h"\n#include <cstdlib>\n#include <string>\n',
    )
    text = once(
        text,
        "  pdcp_metrics_notif->report_metrics(metrics);\n",
        '  const char* trace = std::getenv("OCUDU_PDCP_METRICS_TRACE");\n'
        '  if (trace != nullptr && std::string(trace) == "1") {\n'
        '    logger.log_info("PDCP_METRICS_BATCH tx_counter={} rx_counter={} "\n'
        '                    "rx_sdus={} rx_data_pdus={}",\n'
        "                    m_tx.counter, m_rx.counter, m_rx.num_sdus, m_rx.num_data_pdus);\n"
        "  }\n"
        "  pdcp_metrics_notif->report_metrics(metrics);\n",
    )
    texts[names[7]] = text
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
    print("Statistics timers only; protocol timers and aggregator matching retained.")
    print("Compilation, timer-isolation tests and live source-batch validation pending.")


if __name__ == "__main__":
    main()
