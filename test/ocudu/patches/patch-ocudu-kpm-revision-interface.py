#!/usr/bin/env python3
"""Expose cached RLC source revisions without consuming measurements."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    interface = "include/ocudu/e2/e2sm/e2sm_kpm.h"
    header = "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h"
    texts = {name: (root / name).read_text() for name in (interface, header)}
    if "get_cached_rlc_revisions" in texts[interface]:
        raise SystemExit("STOP: revision interface already present")

    texts[interface] = once(
        texts[interface],
        "  virtual ~e2sm_kpm_meas_provider() = default;",
        """  virtual ~e2sm_kpm_meas_provider() = default;

  /// nullopt: provider does not implement source revision tracking.
  /// Empty list or a zero revision: freshness cannot be established.
  /// Nonzero revisions identify the cached samples, without consuming them.
  virtual std::optional<std::vector<uint64_t>>
  get_cached_rlc_revisions(const asn1::e2sm::ue_id_c& ue)
  {
    return std::nullopt;
  }""",
    )
    if "rlc_source_revisions" not in texts[header]:
        raise SystemExit("STOP: apply the RLC revision patch first")

    texts[header] = once(
        texts[header],
        "  ~e2sm_kpm_du_meas_provider_impl() = default;",
        """  ~e2sm_kpm_du_meas_provider_impl() = default;

  std::optional<std::vector<uint64_t>>
  get_cached_rlc_revisions(const asn1::e2sm::ue_id_c& ue) override
  {
    auto measurement_lock = lock_measurements();
    std::vector<uint64_t> revisions;
    const auto cu_id =
        int_to_gnb_cu_ue_f1ap_id(ue.gnb_du_ue_id().gnb_cu_ue_f1ap_id);
    const uint32_t ue_index = f1ap_ue_id_provider.get_ue_index(cu_id);
    auto cached = ue_aggr_rlc_metrics.find(ue_index);
    if (cached == ue_aggr_rlc_metrics.end()) {
      return revisions;
    }
    for (const auto& sample : cached->second) {
      const auto counter = sample.tx.tx_low.counter;
      if (counter != sample.tx.tx_high.counter ||
          counter != sample.rx.counter) {
        revisions.push_back(0);
        continue;
      }
      const rlc_source_key key{sample.ue_index, sample.rb_id.get_drb_id()};
      auto source = rlc_source_revisions.find(key);
      if (source == rlc_source_revisions.end() ||
          source->second.counter != counter) {
        // Older cached samples cannot be identified by latest-source metadata.
        revisions.push_back(0);
      } else {
        revisions.push_back(source->second.revision);
      }
    }
    return revisions;
  }""",
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
        raise SystemExit("STOP: use an isolated source copy outside Git")
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCHED'}: {name}")


if __name__ == "__main__":
    main()
