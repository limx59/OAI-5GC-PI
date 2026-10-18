#!/usr/bin/env python3
"""Select an optional independent timer factory for KPM subscription reporting."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    header = root / "lib/e2/common/e2_impl.h"
    source = root / "lib/e2/common/e2_impl.cpp"
    h = header.read_text()
    c = source.read_text()
    if "std::optional<timer_factory> kpm_report_timers" not in h:
        raise SystemExit("STOP: apply the clock dependency patch first")

    h = once(
        h,
        "  timer_factory                     timers;\n",
        "  timer_factory                     timers;\n"
        "  std::optional<timer_factory>       kpm_report_timers;\n",
    )
    c = once(
        c,
        '#include "e2_impl.h"\n',
        '#include "e2_impl.h"\n'
        '#include "e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.h"\n',
    )
    c = once(
        c,
        "  timers(dependencies.timers),\n",
        "  timers(dependencies.timers),\n"
        "  kpm_report_timers(dependencies.kpm_report_timers),\n",
    )
    c = once(
        c,
        '  logger.info("Received RIC Subscription Request");\n'
        '  async_tasks.schedule(launch_async<e2ap_subscription_setup_procedure>(\n'
        '      msg, *events, *tx_pdu_notifier, subscription_proc, timers, logger));',
        '  logger.info("Received RIC Subscription Request");\n'
        '  // Change only the timer used by the KPM indication wait.\n'
        '  timer_factory report_timers = timers;\n'
        '  if (msg->ran_function_id == e2sm_kpm_asn1_packer::ran_func_id && kpm_report_timers.has_value()) {\n'
        '    report_timers = kpm_report_timers.value();\n'
        '  }\n'
        '  async_tasks.schedule(launch_async<e2ap_subscription_setup_procedure>(\n'
        '      msg, *events, *tx_pdu_notifier, subscription_proc, report_timers, logger));',
    )
    return {header: h, source: c}


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
        for target, text in texts.items():
            target.write_text(text)
    for target in texts:
        print(f"{'CHECK' if args.check else 'PATCHED'}: {target}")


if __name__ == "__main__":
    main()
