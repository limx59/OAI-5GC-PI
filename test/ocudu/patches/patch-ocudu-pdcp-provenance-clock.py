#!/usr/bin/env python3
"""Export exact steady-clock timestamps for PDCP provenance review."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old[:100]!r}")
    return text.replace(old, new, 1)


def transform(text):
    text = once(
        text,
        "    const auto result = pdcp_history.observe(metrics, pdcp_batch_now());",
        """    const auto received = pdcp_batch_now();
    const auto result = pdcp_history.observe(metrics, received);
    const auto receipt_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
        received.time_since_epoch()).count();""",
    )
    text = once(
        text,
        '"revision={} epoch={} missing={} rx_sdus={} rx_pdus={}",',
        '"revision={} epoch={} missing={} rx_sdus={} rx_pdus={} receipt_ns={}",',
    )
    text = once(
        text,
        "                metrics.rx.num_sdus, metrics.rx.num_data_pdus);",
        "                metrics.rx.num_sdus, metrics.rx.num_data_pdus, receipt_ns);",
    )
    text = once(
        text,
        "  const auto now = pdcp_batch_now();\n",
        """  const auto now = pdcp_batch_now();
  const auto query_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
      now.time_since_epoch()).count();
""",
    )
    text = once(
        text,
        '"rx_pdus={} value=no_value",',
        '"rx_pdus={} value=no_value query_ns={}",',
    )
    text = once(
        text,
        "                query, snapshot.batches.size(), snapshot.expired, sdus, pdus);",
        "                query, snapshot.batches.size(), snapshot.expired, sdus, pdus, query_ns);",
    )
    text = once(
        text,
        '"rx_pdus={} value={}",',
        '"rx_pdus={} value={} query_ns={}",',
    )
    text = once(
        text,
        "                query, snapshot.batches.size(), snapshot.expired, sdus, pdus, percent);",
        "                query, snapshot.batches.size(), snapshot.expired, sdus, pdus, percent, query_ns);",
    )
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    root = options.source_root.resolve()
    if not options.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only to an isolated source copy outside Git")
    path = root / "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_cu_meas_provider_impl.cpp"
    updated = transform(path.read_text())
    if not options.check:
        path.write_text(updated)
    print(f"{'CHECK' if options.check else 'PATCHED'}: exact PDCP provenance clocks")


if __name__ == "__main__":
    main()
