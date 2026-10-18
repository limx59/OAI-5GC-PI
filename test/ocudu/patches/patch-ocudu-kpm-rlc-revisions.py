#!/usr/bin/env python3
"""Track RLC source revisions in an isolated, collection-locked source copy."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    prefix = "lib/e2/e2sm/e2sm_kpm/"
    header = prefix + "e2sm_kpm_du_meas_provider_impl.h"
    source = prefix + "e2sm_kpm_du_meas_provider_impl.cpp"
    h = (root / header).read_text()
    c = (root / source).read_text()

    if "measurement_mutex" not in h:
        raise SystemExit("STOP: apply the collection-lock patch first")
    if "rlc_source_revisions" in h:
        raise SystemExit("STOP: revision tracking already present")

    h = once(h, "#include <deque>",
             "#include <deque>\n#include <chrono>\n#include <cstdint>\n#include <utility>")
    h = once(
        h,
        "  ~e2sm_kpm_du_meas_provider_impl() = default;",
        """  ~e2sm_kpm_du_meas_provider_impl() = default;

  /// Inspect a source revision without consuming shared measurements.
  std::optional<uint64_t> get_rlc_source_revision(uint16_t ue, drb_id_t bearer)
  {
    auto measurement_lock = lock_measurements();
    auto source = rlc_source_revisions.find(rlc_source_key{ue, bearer});
    if (source == rlc_source_revisions.end()) {
      return std::nullopt;
    }
    return source->second.revision;
  }""",
    )
    h = once(h, "private:\n", """private:
  struct rlc_source_revision {
    uint32_t counter;
    uint64_t revision;
    std::chrono::steady_clock::time_point received_at;
  };

  // Separate bearer counters; equal values on different bearers are unrelated.
  using rlc_source_key = std::pair<uint16_t, drb_id_t>;
  std::map<rlc_source_key, rlc_source_revision> rlc_source_revisions;
  uint64_t next_rlc_revision = 0;

""")

    anchor = "  ue_aggr_rlc_metrics[metrics.ue_index].push_back(metrics);"
    addition = """  // This timestamp is local receipt time, not radio collection time.
  // Use the matched component counter until the collector counter fix is deployed.
  const rlc_source_key source_key{metrics.ue_index, metrics.rb_id.get_drb_id()};
  const uint32_t source_counter = metrics.tx.tx_low.counter;
  if (source_counter == metrics.tx.tx_high.counter &&
      source_counter == metrics.rx.counter) {
    auto previous = rlc_source_revisions.find(source_key);
    if (previous == rlc_source_revisions.end() ||
        previous->second.counter != source_counter) {
      rlc_source_revisions[source_key] =
          rlc_source_revision{source_counter, ++next_rlc_revision,
                              std::chrono::steady_clock::now()};
    }
  }

"""
    c = once(c, anchor, addition + anchor)

    anchor = "      it = ue_aggr_rlc_metrics.erase(it);"
    addition = """      for (auto revision = rlc_source_revisions.begin();
           revision != rlc_source_revisions.end();) {
        if (revision->first.first == it->first) {
          revision = rlc_source_revisions.erase(revision);
        } else {
          ++revision;
        }
      }
"""
    c = once(c, anchor, addition + anchor)
    return {header: h, source: c}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: use an isolated source copy outside Git")
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCHED'}: {name}")
    print("Metadata only; freshness filtering and UE-index reuse handling remain pending.")


if __name__ == "__main__":
    main()
