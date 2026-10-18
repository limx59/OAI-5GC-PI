#!/usr/bin/env python3
"""Add an optional RLC metrics clock without changing protocol timer factories."""

import argparse
from pathlib import Path
import re


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new)


def regex(text, pattern, replacement):
    updated, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise SystemExit(f"STOP: unexpected pattern count {count}: {pattern}")
    return updated


def transform(root):
    names = [
        "include/ocudu/rlc/rlc_factory.h",
        "lib/rlc/rlc_factory.cpp",
        "lib/rlc/rlc_base_entity.h",
        "lib/rlc/rlc_bearer_metrics_collector.h",
        "lib/rlc/rlc_bearer_metrics_collector.cpp",
        "lib/rlc/rlc_rx_entity.h",
        "lib/rlc/rlc_tx_entity.h",
        "lib/rlc/rlc_am_entity.h",
        "lib/rlc/rlc_um_entity.h",
        "lib/rlc/rlc_tm_entity.h",
    ]
    texts = {name: (root / name).read_text() for name in names}
    if any("select_metrics_timers" in text for text in texts.values()):
        raise SystemExit("STOP: metrics clock patch already present")

    name = names[0]
    texts[name] = replace(
        texts[name], "\n};",
        "\n  // Optional clock for metrics only; lifetime must cover the bearer.\n"
        "  timer_manager* metrics_timers = nullptr;\n};",
    )

    name = names[1]
    texts[name] = replace(
        texts[name], "*msg.pdu_recycler);",
        "*msg.pdu_recycler,\n"
        "                                             msg.metrics_timers);",
        count=3,
    )

    name = names[2]
    texts[name] = regex(
        texts[name], r"(task_executor&\s+ue_executor_)\) :",
        r"\1,\n                  timer_manager* metrics_timers_ = nullptr) :",
    )
    texts[name] = replace(
        texts[name],
        "metrics_coll(gnb_du_id_, ue_index, rb_id_, metrics_period_, rlc_metrics_notifier_, ue_executor_)",
        "metrics_coll(gnb_du_id_, ue_index, rb_id_, metrics_period_, "
        "rlc_metrics_notifier_, ue_executor_, metrics_timers_)",
    )

    name = names[3]
    texts[name] = replace(
        texts[name], '#include "ocudu/rlc/rlc_metrics.h"',
        '#include "ocudu/rlc/rlc_metrics.h"\n'
        '#include "ocudu/support/timers.h"',
    )
    texts[name] = regex(
        texts[name], r"(task_executor&\s+ue_executor_)\);",
        r"\1,\n                               timer_manager* metrics_timers_ = nullptr);",
    )
    texts[name] = replace(
        texts[name], "private:\n",
        """  /// Preserve protocol timer factories; select only metrics timers.
  timer_manager& select_metrics_timers(timer_manager& protocol_timers) const
  {
    return metrics_timers != nullptr ? *metrics_timers : protocol_timers;
  }

private:
""",
    )
    texts[name] = replace(
        texts[name], "  rlc_bearer_logger logger;",
        "  timer_manager* metrics_timers;\n\n  rlc_bearer_logger logger;",
    )

    name = names[4]
    texts[name] = regex(
        texts[name], r"(task_executor&\s+ue_executor_)\) :",
        r"\1,\n                                                           timer_manager* metrics_timers_) :",
    )
    texts[name] = replace(
        texts[name], "  ue_executor(ue_executor_),",
        "  ue_executor(ue_executor_),\n  metrics_timers(metrics_timers_),",
    )

    name = names[5]
    texts[name] = replace(
        texts[name], "high_metrics_timer(ue_timer_factory.create_timer()),",
        "high_metrics_timer(timer_factory{metrics_coll_.select_metrics_timers(timers), "
        "ue_executor_}.create_timer()),",
    )

    name = names[6]
    texts[name] = replace(
        texts[name], "high_metrics_timer(ue_timer_factory.create_timer()),",
        "high_metrics_timer(timer_factory{metrics_coll_.select_metrics_timers(timers), "
        "ue_executor}.create_timer()),",
    )
    texts[name] = replace(
        texts[name], "low_metrics_timer(pcell_timer_factory.create_timer()),",
        "low_metrics_timer(timer_factory{metrics_coll_.select_metrics_timers(timers), "
        "pcell_executor}.create_timer()),",
    )

    for name in names[7:]:
        texts[name] = regex(
            texts[name], r"(byte_buffer_recycler&\s+pdu_recycler)\) :",
            r"\1,\n                timer_manager* metrics_timers = nullptr) :",
        )
        texts[name] = replace(
            texts[name],
            "rlc_base_entity(gnb_du_id_, ue_index_, rb_id_, metrics_period_, rlc_metrics_notifier_, ue_executor)",
            "rlc_base_entity(gnb_du_id_, ue_index_, rb_id_, metrics_period_, "
            "rlc_metrics_notifier_, ue_executor, metrics_timers)",
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
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCHED'}: {name}")
    print("Optional clock only; application wiring and validation pending.")


if __name__ == "__main__":
    main()
