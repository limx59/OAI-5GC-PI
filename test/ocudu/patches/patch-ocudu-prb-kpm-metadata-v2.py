#!/usr/bin/env python3
"""Export laboratory PRB provenance through named KPM measurements."""
import argparse
from pathlib import Path

NAMES = (
    "OAI.PI.PrbSourceRevision",
    "OAI.PI.PrbReceiptMonoSec",
    "OAI.PI.PrbReceiptMonoUsec",
    "OAI.PI.PrbQueryMonoSec",
    "OAI.PI.PrbQueryMonoUsec",
)

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)

def transform(root):
    prefix = root / "lib/e2/e2sm/e2sm_kpm"
    path = prefix / "e2sm_kpm_du_meas_provider_impl.cpp"
    header = (prefix / "e2sm_kpm_du_meas_provider_impl.h").read_text()
    text = path.read_text()
    if "prb_metadata_query_time" in header:
        raise RuntimeError("Query snapshot already present")
    header = once(
        header, "private:\n",
        "private:\n"
        "  std::chrono::steady_clock::time_point prb_metadata_query_time{};\n",
    )
    service = (prefix / "e2sm_kpm_report_service_impl.cpp").read_text()

    if NAMES[0] in text:
        raise RuntimeError("Metadata patch already present")
    if "prb_trace_revision" not in header or "prb_trace_received" not in header:
        raise RuntimeError("Apply PRB source-trace prerequisite first")

    start = service.index(
        "bool e2sm_kpm_report_service_style4::collect_measurements()"
    )
    end = service.index("e2sm_kpm_report_service_style5::", start)
    body = service[start:end]
    lock = body.find("auto measurement_lock = meas_provider.lock_measurements();")
    loop = body.find("for (auto& meas_info : meas_info_list)")
    if not 0 <= lock < loop:
        raise RuntimeError("Style 4 whole-row measurement lock missing")

    registration = ""
    for name in NAMES:
        registration += (
            '  supported_metrics.emplace(\n'
            f'      "{name}",\n'
            '      e2sm_kpm_supported_metric_t{\n'
            '          NO_LABEL, E2_NODE_LEVEL | UE_LEVEL, true,\n'
            '          &e2sm_kpm_du_meas_provider_impl::get_prb_use_perc_dl});\n'
        )
    anchor = "  // Check if the supported metrics are matching e2sm_kpm metrics definitions."
    text = once(text, anchor,
                "  // Laboratory provenance extensions; not standardized metrics.\n"
                + registration + "\n" + anchor)

    addition = """
  // PRB and provenance are collected under the existing Style 4 row lock.
  const auto provenance_name = meas_type.meas_name().to_string();
  if (provenance_name == "OAI.PI.PrbSourceRevision" ||
      provenance_name == "OAI.PI.PrbReceiptMonoSec" ||
      provenance_name == "OAI.PI.PrbReceiptMonoUsec" ||
      provenance_name == "OAI.PI.PrbQueryMonoSec" ||
      provenance_name == "OAI.PI.PrbQueryMonoUsec") {
    if (provenance_name == "OAI.PI.PrbSourceRevision") {
      prb_metadata_query_time = std::chrono::steady_clock::now();
    }
    const auto now = prb_metadata_query_time;
    if (!get_prb_use_perc_dl(label_info_list, ues, cell_global_id, items)) {
      return false;
    }
    for (auto& item : items) {
      // Preserve unavailable UE records; never invent provenance.
      if (item.type() != meas_record_item_c::types_opts::integer ||
          prb_trace_revision == 0 || prb_trace_revision > 2147483647ULL) {
        item.set_no_value();
        continue;
      }
      if (provenance_name == "OAI.PI.PrbSourceRevision") {
        item.set_integer() = prb_trace_revision;
      } else {
        const bool receipt_metric =
            provenance_name == "OAI.PI.PrbReceiptMonoSec" ||
            provenance_name == "OAI.PI.PrbReceiptMonoUsec";
        const auto stamp = receipt_metric ? prb_trace_received : now;
        const auto micros =
            std::chrono::duration_cast<std::chrono::microseconds>(
                stamp.time_since_epoch()).count();
        const bool seconds_metric =
            provenance_name == "OAI.PI.PrbReceiptMonoSec" ||
            provenance_name == "OAI.PI.PrbQueryMonoSec";
        if (micros < 0 || micros / 1000000 > 2147483647LL) {
          item.set_no_value();
        } else {
          item.set_integer() =
              seconds_metric ? micros / 1000000 : micros % 1000000;
        }
      }
    }
    return true;
  }

"""
    signature = "bool e2sm_kpm_du_meas_provider_impl::get_meas_data("
    start = text.index(signature)
    anchor = "  metric_meas_getter_func_ptr metric_meas_getter_func;"
    end = text.index(anchor, start)
    if "lock_measurements()" not in text[start:end]:
        raise RuntimeError("Provider measurement lock missing")
    text = once(text, anchor, addition + anchor)
    return {
        prefix / "e2sm_kpm_du_meas_provider_impl.h": header,
        path: text,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (p / ".git").exists() for p in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only to an isolated build copy")
    updates = transform(root)
    for path, text in updates.items():
        if not args.check:
            path.write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ") + str(path))
    print("Laboratory provenance only; existing PRB values unchanged.")

if __name__ == "__main__":
    main()
