#!/usr/bin/env python3
"""Trace scheduler-source receipt and PRB cache reads in a build copy."""
import argparse
from pathlib import Path

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)

def transform(root):
    prefix = "lib/e2/e2sm/e2sm_kpm/"
    header = prefix + "e2sm_kpm_du_meas_provider_impl.h"
    source = prefix + "e2sm_kpm_du_meas_provider_impl.cpp"
    h = (root / header).read_text()
    c = (root / source).read_text()
    if "prb_trace_revision" in h:
        raise RuntimeError("PRB trace already present")
    if "measurement_mutex" not in h:
        raise RuntimeError("Collection-lock prerequisite missing")

    # Both accesses must remain under the existing collection lock.
    for signature, anchor in (
        ("void e2sm_kpm_du_meas_provider_impl::report_metrics(const scheduler_cell_metrics&",
         "  last_ue_metrics.clear();"),
        ("bool e2sm_kpm_du_meas_provider_impl::get_meas_data(",
         "  metric_meas_getter_func_ptr metric_meas_getter_func;"),
    ):
        start = c.index(signature)
        end = c.index(anchor, start)
        if "lock_measurements()" not in c[start:end]:
            raise RuntimeError("Expected existing measurement lock missing")

    h = once(h, "#include <deque>",
             "#include <deque>\n#include <chrono>\n#include <cstdint>")
    h = once(h, "private:\n", """private:
  // Diagnostic metadata only; receipt time is not collection-window time.
  uint64_t prb_trace_revision = 0;
  std::chrono::steady_clock::time_point prb_trace_received{};
""")
    c = '#include <cstdio>\n#include <cstdlib>\n' + c

    anchor = "  last_ue_metrics.clear();"
    addition = """  const char* trace = std::getenv("OCUDU_PRB_SOURCE_TRACE");
  if (trace != nullptr && std::string(trace) == "1") {
    prb_trace_received = std::chrono::steady_clock::now();
    ++prb_trace_revision;
    const auto mono_us = std::chrono::duration_cast<std::chrono::microseconds>(
        prb_trace_received.time_since_epoch()).count();
    const auto utc_us = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    std::fprintf(stderr,
        "PRB_SOURCE revision=%llu receipt_mono_us=%lld receipt_utc_us=%lld "
        "start_slot=%u nof_slots=%u dl_slots=%u ul_slots=%u ue_count=%zu\\n",
        static_cast<unsigned long long>(prb_trace_revision),
        static_cast<long long>(mono_us), static_cast<long long>(utc_us),
        static_cast<unsigned>(cell_metrics.slot.count()),
        static_cast<unsigned>(cell_metrics.nof_slots),
        static_cast<unsigned>(cell_metrics.nof_dl_slots),
        static_cast<unsigned>(cell_metrics.nof_ul_slots),
        cell_metrics.ue_metrics.size());
  }

"""
    c = once(c, anchor, addition + anchor)

    anchor = "  metric_meas_getter_func_ptr metric_meas_getter_func;"
    addition = """  const char* trace = std::getenv("OCUDU_PRB_SOURCE_TRACE");
  const auto trace_metric = meas_type.meas_name().to_string();
  if (trace != nullptr && std::string(trace) == "1" &&
      trace_metric == "RRU.PrbTotDl") {
    const auto now = std::chrono::steady_clock::now();
    const auto mono_us = std::chrono::duration_cast<std::chrono::microseconds>(
        now.time_since_epoch()).count();
    const auto utc_us = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    const auto age_us = prb_trace_revision == 0 ? -1LL :
        static_cast<long long>(
            std::chrono::duration_cast<std::chrono::microseconds>(
                now - prb_trace_received).count());
    std::fprintf(stderr,
        "PRB_QUERY metric=RRU.PrbTotDl revision=%llu query_mono_us=%lld "
        "query_utc_us=%lld receipt_age_us=%lld requested_ues=%zu\\n",
        static_cast<unsigned long long>(prb_trace_revision),
        static_cast<long long>(mono_us), static_cast<long long>(utc_us),
        age_us, ues.size());
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
        raise SystemExit("STOP: apply only to an isolated build copy")
    updates = transform(root)
    for name, text in updates.items():
        if not args.check:
            (root / name).write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ") + name)

if __name__ == "__main__":
    main()
