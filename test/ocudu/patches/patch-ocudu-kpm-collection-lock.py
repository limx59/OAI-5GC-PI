#!/usr/bin/env python3
"""Serialize DU KPM cache access in an isolated Docker source copy."""

import argparse
from pathlib import Path
import re


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: expected one anchor: {old[:100]!r}")
    return text.replace(old, new, 1)


def lock_functions(text, owner, name, count, statement):
    pattern = (
        r"(" + re.escape(owner + "::" + name)
        + r"\([^;{]*\)\s*\n\{\n)"
    )
    if len(re.findall(pattern, text)) != count:
        raise SystemExit(f"STOP: unexpected function count: {owner}::{name}")
    return re.sub(pattern, lambda m: m[1] + statement, text)


def transform(root):
    names = [
        "include/ocudu/e2/e2sm/e2sm_kpm.h",
        "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h",
        "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp",
        "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp",
    ]
    texts = {name: (root / name).read_text() for name in names}
    if any("lock_measurements" in text or "measurement_mutex" in text
           for text in texts.values()):
        raise SystemExit("STOP: synchronization patch already present")

    name = names[0]
    texts[name] = once(
        texts[name],
        '#include "ocudu/asn1/e2sm/e2sm_rc_ies.h"',
        '#include "ocudu/asn1/e2sm/e2sm_rc_ies.h"\n#include <mutex>',
    )
    texts[name] = once(
        texts[name],
        "  virtual ~e2sm_kpm_meas_provider() = default;",
        """  virtual ~e2sm_kpm_meas_provider() = default;

  /// Hold a stable cache view during synchronous measurement collection.
  /// Release before encoding; never retain across an await or executor hop.
  /// Other providers retain their existing serialization contract.
  virtual std::unique_lock<std::recursive_mutex> lock_measurements() { return {}; }""",
    )

    name = names[1]
    texts[name] = once(
        texts[name],
        "  ~e2sm_kpm_du_meas_provider_impl() = default;",
        """  ~e2sm_kpm_du_meas_provider_impl() = default;

  std::unique_lock<std::recursive_mutex> lock_measurements() override
  {
    return std::unique_lock<std::recursive_mutex>{measurement_mutex};
  }""",
    )
    texts[name] = once(
        texts[name], "private:\n",
        """private:
  // Recursive for collection -> getter and scheduler update -> cleanup.
  std::recursive_mutex measurement_mutex;

""",
    )

    name = names[2]
    for function, count in (
        ("report_metrics", 2),
        ("clear_rlc_metrics", 1),
        ("get_ues_matching_test_conditions", 2),
        ("get_meas_data", 1),
    ):
        texts[name] = lock_functions(
            texts[name], "e2sm_kpm_du_meas_provider_impl",
            function, count,
            "  auto measurement_lock = lock_measurements();\n",
        )

    name = names[3]
    marker = "Skipping Style 4 report: measurement collection failed or record count mismatched"
    if marker not in texts[name]:
        raise SystemExit("STOP: apply the Style 4 record guard first")
    for style in range(1, 6):
        texts[name] = lock_functions(
            texts[name], f"e2sm_kpm_report_service_style{style}",
            "collect_measurements", 1,
            "  auto measurement_lock = meas_provider.lock_measurements();\n",
        )
    return texts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: use an isolated source copy, not a Git working tree")
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("Clock, period, metric formulas and freshness policy unchanged.")


if __name__ == "__main__":
    main()
