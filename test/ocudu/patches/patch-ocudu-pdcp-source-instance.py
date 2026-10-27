#!/usr/bin/env python3
"""Identify PDCP aggregator instances and recover batch history on replacement."""

import argparse
from pathlib import Path

FILES = (
    "include/ocudu/pdcp/pdcp_entity.h",
    "lib/pdcp/pdcp_metrics_aggregator.h",
    "lib/pdcp/pdcp_metrics_aggregator.cpp",
    "lib/e2/e2sm/e2sm_kpm/pdcp_batch_history.h",
)


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old[:100]!r}")
    return text.replace(old, new, 1)


def transform(original):
    updated = dict(original)
    entity, header, source, history = FILES

    updated[entity] = once(
        updated[entity],
        "  timer_duration            metrics_period;\n",
        "  timer_duration            metrics_period;\n"
        "  // Process-local aggregator identity; zero means unspecified.\n"
        "  uint64_t source_instance = 0;\n",
    )

    updated[header] = once(
        updated[header],
        "  rb_id_t                   rb_id;\n",
        "  rb_id_t                   rb_id;\n"
        "  const uint64_t            source_instance;\n",
    )

    allocator = """
#include <atomic>
#include <limits>
#include <stdexcept>

namespace {
uint64_t allocate_pdcp_source_instance()
{
  static std::atomic<uint64_t> sequence{0};
  uint64_t previous = sequence.load(std::memory_order_relaxed);
  for (;;) {
    if (previous == std::numeric_limits<uint64_t>::max()) {
      throw std::overflow_error("PDCP source instance exhausted");
    }
    if (sequence.compare_exchange_weak(
            previous, previous + 1, std::memory_order_relaxed)) {
      return previous + 1;
    }
  }
}
} // namespace
"""
    updated[source] = once(
        updated[source],
        '#include "ocudu/pdcp/pdcp_entity.h"\n',
        '#include "ocudu/pdcp/pdcp_entity.h"\n' + allocator,
    )
    updated[source] = once(
        updated[source],
        "  rb_id(rb_id_),\n",
        "  rb_id(rb_id_),\n"
        "  source_instance(allocate_pdcp_source_instance()),\n",
    )
    updated[source] = once(
        updated[source],
        "  pdcp_metrics_container metrics = "
        "{ue_index, rb_id, m_tx, m_rx, metrics_period};\n",
        "  pdcp_metrics_container metrics = "
        "{ue_index, rb_id, m_tx, m_rx, metrics_period};\n"
        "  metrics.source_instance = source_instance;\n",
    )

    updated[history] = once(
        updated[history],
        "    time_regression\n",
        "    time_regression,\n"
        "    source_restart,\n"
        "    stale_source\n",
    )
    updated[history] = once(
        updated[history],
        "    disposition status = disposition::accepted;\n",
        """    // Identity is allocated by the aggregator, independently of counters.
    // Once an identified source is seen, unidentified/older inputs are stale.
    if (metrics.source_instance < state.source_instance) {
      return {disposition::stale_source, 0, state.epoch, 0, false};
    }
    bool restarted = false;
    if (metrics.source_instance > state.source_instance) {
      restarted = state.has_counter || state.source_instance != 0;
      if (restarted) {
        begin_epoch(key(metrics));
      }
      state.source_instance = metrics.source_instance;
    }

    disposition status = restarted
        ? disposition::source_restart : disposition::accepted;
""",
    )
    updated[history] = once(
        updated[history],
        "    uint64_t epoch = 1;\n",
        "    uint64_t epoch = 1;\n"
        "    uint64_t source_instance = 0;\n",
    )
    return updated


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
    original = {name: (root / name).read_text() for name in FILES}
    updated = transform(original)
    for name in FILES:
        if not args.check:
            (root / name).write_text(updated[name])
        print(f"{'CHECK' if args.check else 'PATCHED'}: {name}")
    print("Aggregator replacement only; C++ and runtime validation pending.")


if __name__ == "__main__":
    main()
