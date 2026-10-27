#!/usr/bin/env python3
"""Inject opt-in PDCP metrics delivery faults in isolated test images."""

import argparse
from pathlib import Path


def transform(text):
    anchor = "  pdcp_metrics_notif->report_metrics(metrics);\n"
    if text.count(anchor) != 1:
        raise SystemExit("STOP: unexpected PDCP delivery anchor")
    if "metrics.source_instance = source_instance;" not in text:
        raise SystemExit("STOP: source-instance patch is required")
    if "PDCP_DELIVERY_FAULT" in text:
        raise SystemExit("STOP: delivery fault patch already present")

    replacement = """  // Test-only statistics delivery faults; PDCP traffic is unchanged.
  const char* delivery_fault_option =
      std::getenv("OCUDU_PDCP_TEST_DELIVERY_FAULT");
  const std::string delivery_fault =
      delivery_fault_option != nullptr ? delivery_fault_option : "";
  const bool selected_delivery =
      metrics.rb_id.is_drb() &&
      metrics.tx.counter == metrics.rx.counter &&
      metrics.rx.counter % 10U == 5U;

  if (selected_delivery && delivery_fault == "drop") {
    logger.log_info(
        "PDCP_DELIVERY_FAULT action=drop ue={} rb={} instance={} counter={}",
        metrics.ue_index, metrics.rb_id, metrics.source_instance,
        metrics.rx.counter);
    return;
  }

  pdcp_metrics_notif->report_metrics(metrics);

  if (selected_delivery && delivery_fault == "duplicate") {
    logger.log_info(
        "PDCP_DELIVERY_FAULT action=duplicate ue={} rb={} instance={} counter={}",
        metrics.ue_index, metrics.rb_id, metrics.source_instance,
        metrics.rx.counter);
    pdcp_metrics_notif->report_metrics(metrics);
  }
"""
    return text.replace(anchor, replacement, 1)


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
    print(f"{'CHECK' if args.check else 'PATCHED'}: PDCP delivery fault injection")
    print("Disabled unless OCUDU_PDCP_TEST_DELIVERY_FAULT=duplicate or drop.")


if __name__ == "__main__":
    main()
