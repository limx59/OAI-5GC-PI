#!/usr/bin/env python3
"""Reject reused RLC samples in Style 4 throughput records."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    prefix = "lib/e2/e2sm/e2sm_kpm/"
    header = prefix + "e2sm_kpm_report_service_impl.h"
    source = prefix + "e2sm_kpm_report_service_impl.cpp"
    h = (root / header).read_text()
    c = (root / source).read_text()
    interface = (root / "include/ocudu/e2/e2sm/e2sm_kpm.h").read_text()
    if "get_cached_rlc_revisions" not in interface:
        raise SystemExit("STOP: apply the revision interface patch first")
    if "last_rlc_revision_by_ue" in h:
        raise SystemExit("STOP: freshness patch already present")

    start = h.index("class e2sm_kpm_report_service_style4 ")
    end = h.index("class e2sm_kpm_report_service_style5 ", start)
    section = h[start:end]
    section = once(
        section, "private:\n",
        "private:\n"
        "  // Subscription-local watermarks; shared samples are never consumed.\n"
        "  std::map<uint64_t, uint64_t> last_rlc_revision_by_ue;\n\n",
    )
    h = h[:start] + section + h[end:]

    start = c.index("bool e2sm_kpm_report_service_style4::collect_measurements()\n")
    end = c.index("e2sm_kpm_report_service_style5::", start)
    body = c[start:end]
    body = once(
        body,
        "  auto measurement_lock = meas_provider.lock_measurements();\n",
        "  auto measurement_lock = meas_provider.lock_measurements();\n"
        "  auto pending_revisions = last_rlc_revision_by_ue;\n",
    )
    body = once(
        body,
        "    // Put each measurement record into a proper place.\n",
        """    const auto metric_name = meas_info.meas_type.meas_name().to_string();
    if (metric_name == "DRB.UEThpDl" || metric_name == "DRB.UEThpUl") {
      for (unsigned index = 0; index != all_matching_ues.size(); ++index) {
        auto revisions = meas_provider.get_cached_rlc_revisions(all_matching_ues[index]);
        if (!revisions.has_value()) {
          // Preserve behavior for providers without revision support.
          continue;
        }
        const uint64_t ue_key =
            all_matching_ues[index].gnb_du_ue_id().gnb_cu_ue_f1ap_id;
        auto previous = last_rlc_revision_by_ue.find(ue_key);
        const uint64_t watermark =
            previous == last_rlc_revision_by_ue.end() ? 0 : previous->second;
        bool fresh = !revisions->empty();
        uint64_t newest = watermark;
        for (uint64_t revision : *revisions) {
          // Overlapping history is conservatively unavailable.
          fresh = fresh && revision != 0 && revision > watermark;
          newest = std::max(newest, revision);
        }
        auto& record = meas_records_items[index];
        if (!fresh) {
          record.set_no_value();
        } else if (record.type() == meas_record_item_c::types_opts::integer ||
                   record.type() == meas_record_item_c::types_opts::real) {
          pending_revisions[ue_key] = newest;
        }
      }
    }

    // Put each measurement record into a proper place.
""",
    )
    body = once(
        body,
        "  nof_collected_meas_data++;\n",
        "  // Commit only after every requested metric was collected successfully.\n"
        "  last_rlc_revision_by_ue = std::move(pending_revisions);\n"
        "  nof_collected_meas_data++;\n",
    )
    c = c[:start] + body + c[end:]
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
    print("Style 4 throughput only; source age and UE identity reuse remain pending.")


if __name__ == "__main__":
    main()
