#!/usr/bin/env python3
"""Replay one real old-source metrics report in an opt-in test image."""

import argparse
from pathlib import Path


def transform(text):
    if "PDCP_LATE_SOURCE_FAULT" in text:
        raise SystemExit("STOP: late-source patch already present")
    if "metrics.source_instance = source_instance;" not in text:
        raise SystemExit("STOP: source-instance patch is required")

    anchor = '  if (selected_delivery && delivery_fault == "duplicate") {\n'
    if text.count(anchor) != 1:
        raise SystemExit("STOP: unexpected delivery-fault anchor")

    addition = """  // Process-local test state shared across aggregator reconstruction.
  // Copy reports under the lock; deliver them only after releasing the lock.
  const char* late_source_option =
      std::getenv("OCUDU_PDCP_TEST_LATE_SOURCE");
  if (late_source_option != nullptr &&
      std::string(late_source_option) == "1" &&
      metrics.rb_id.is_drb() &&
      metrics.tx.counter == metrics.rx.counter &&
      metrics.source_instance != 0) {
    static std::mutex late_source_mutex;
    static std::optional<pdcp_metrics_container> old_source_report;
    static bool late_source_sent = false;
    std::optional<pdcp_metrics_container> replay;
    {
      std::lock_guard<std::mutex> lock(late_source_mutex);
      if (!old_source_report.has_value() &&
          metrics.rx.num_data_pdus > 0) {
        old_source_report = metrics;
      }
      if (old_source_report.has_value() &&
          metrics.ue_index == old_source_report->ue_index &&
          old_source_report->rb_id.is_drb() &&
          metrics.rb_id.get_drb_id() ==
              old_source_report->rb_id.get_drb_id()) {
        if (metrics.source_instance == old_source_report->source_instance &&
            metrics.rx.num_data_pdus > 0 && !late_source_sent) {
          old_source_report = metrics;
        } else if (metrics.source_instance >
                       old_source_report->source_instance &&
                   metrics.rx.counter >= 15U && !late_source_sent &&
                   std::ifstream("/tmp/ocudu-pdcp-late-source.arm").good()) {
          replay = old_source_report;
          late_source_sent = true;
        }
      }
    }
    if (replay.has_value()) {
      logger.log_info(
          "PDCP_LATE_SOURCE_FAULT ue={} rb={} old_instance={} "
          "new_instance={} old_counter={} new_counter={} "
          "rx_sdus={} rx_pdus={}",
          metrics.ue_index, metrics.rb_id,
          replay->source_instance, metrics.source_instance,
          replay->rx.counter, metrics.rx.counter,
          replay->rx.num_sdus, replay->rx.num_data_pdus);
      pdcp_metrics_notif->report_metrics(*replay);
    }
  }

"""
    text = text.replace(anchor, addition + anchor, 1)
    include = text.find("#include ")
    if include < 0:
        raise SystemExit("STOP: include anchor missing")
    return (
        text[:include] + "#include <mutex>\n#include <optional>\n#include <fstream>\n"
        + text[include:]
    )


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
    path = root / "lib/pdcp/pdcp_metrics_aggregator.cpp"
    updated = transform(path.read_text())
    if not args.check:
        path.write_text(updated)
    print(f"{'CHECK' if args.check else 'PATCHED'}: late old-source replay")
    print("Disabled unless OCUDU_PDCP_TEST_LATE_SOURCE=1.")


if __name__ == "__main__":
    main()
