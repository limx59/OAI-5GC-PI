#!/usr/bin/env python3
"""Add opt-in CU-UP PDCP batch history and calculation provenance."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old[:100]!r}")
    return text.replace(old, new, 1)


def transform(root):
    header = "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_cu_meas_provider_impl.h"
    source = "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_cu_meas_provider_impl.cpp"
    h = (root / header).read_text()
    c = (root / source).read_text()
    if "pdcp_batch_history_enabled" in h:
        raise SystemExit("STOP: PDCP batch-history wiring already present")

    h = once(
        h, '#include "e2sm_kpm_utils.h"\n',
        '#include "e2sm_kpm_utils.h"\n#include "pdcp_batch_history.h"\n',
    )
    h = once(h, "protected:\n", """protected:
  // Tests override time without sleeps. Production uses monotonic receipt age.
  virtual pdcp_batch_history::time_point pdcp_batch_now() const
  {
    return pdcp_batch_history::clock::now();
  }

  bool get_packet_success_from_batches(
      const asn1::e2sm::label_info_list_l& labels,
      const std::vector<asn1::e2sm::ue_id_c>& ues,
      const std::optional<asn1::e2sm::cgi_c>& cell,
      std::vector<asn1::e2sm::meas_record_item_c>& items);

  bool pdcp_batch_history_enabled = false;
  pdcp_batch_history pdcp_history;
  std::mutex pdcp_history_mutex;
  uint64_t pdcp_query_sequence = 0;

""")
    c = once(
        c, "#include <algorithm>\n",
        "#include <algorithm>\n#include <cstdlib>\n#include <string>\n",
    )
    c = once(
        c,
        'e2sm_kpm_cu_meas_provider_impl::e2sm_kpm_cu_meas_provider_impl() : logger(ocudulog::fetch_basic_logger("E2SM-KPM")) {}',
        """e2sm_kpm_cu_meas_provider_impl::e2sm_kpm_cu_meas_provider_impl() :
  logger(ocudulog::fetch_basic_logger("E2SM-KPM"))
{
  const char* option = std::getenv("OCUDU_PDCP_BATCH_HISTORY");
  pdcp_batch_history_enabled = option != nullptr && std::string(option) == "1";
  if (pdcp_batch_history_enabled) {
    logger.info("Experimental PDCP batch history enabled: receipt_age_ms=2500 capacity_per_source=10");
  }
}""",
    )

    anchor = (
        "void e2sm_kpm_cu_meas_provider_impl::report_metrics(const pdcp_metrics_container& metrics)\n"
        "{\n"
    )
    addition = """  if (pdcp_batch_history_enabled) {
    std::lock_guard<std::mutex> lock(pdcp_history_mutex);
    const auto result = pdcp_history.observe(metrics, pdcp_batch_now());
    logger.info("PDCP_BATCH_INPUT ue={} rb={} tx={} rx={} status={} accepted={} "
                "revision={} epoch={} missing={} rx_sdus={} rx_pdus={}",
                metrics.ue_index, metrics.rb_id, metrics.tx.counter, metrics.rx.counter,
                static_cast<unsigned>(result.status), result.accepted,
                result.revision, result.epoch, result.missing,
                metrics.rx.num_sdus, metrics.rx.num_data_pdus);
    // Other getters retain their legacy cache semantics.
    if (!result.accepted) {
      return;
    }
  }
"""
    c = once(c, anchor, anchor + addition)

    marker = (
        "bool e2sm_kpm_cu_meas_provider_impl::"
        "get_packet_success_rate_ul_gnb_uu("
    )
    if c.count(marker) != 1:
        raise SystemExit("STOP: unexpected success-rate getter")
    start = c.index(marker)
    opening = c.index("{\n", start) + 2
    c = c[:opening] + """  if (pdcp_batch_history_enabled) {
    return get_packet_success_from_batches(label_info_list, ues, cell_global_id, items);
  }
""" + c[opening:]

    implementation = r"""
bool e2sm_kpm_cu_meas_provider_impl::get_packet_success_from_batches(
    const label_info_list_l& labels,
    const std::vector<ue_id_c>& ues,
    const std::optional<cgi_c>& cell,
    std::vector<meas_record_item_c>& items)
{
  if (!ues.empty() || cell.has_value() || labels.size() > 1 ||
      (labels.size() == 1 && !labels[0].meas_label.no_label_present)) {
    return false;
  }

  std::lock_guard<std::mutex> lock(pdcp_history_mutex);
  const auto now = pdcp_batch_now();
  const auto snapshot = pdcp_history.collect(now);
  const uint64_t query = ++pdcp_query_sequence;
  uint64_t sdus = 0;
  uint64_t pdus = 0;
  for (const auto& batch : snapshot.batches) {
    sdus += batch.metrics.rx.num_sdus;
    pdus += batch.metrics.rx.num_data_pdus;
    const auto age = std::chrono::duration_cast<std::chrono::milliseconds>(
        now - batch.received).count();
    logger.info("PDCP_KPM_SOURCE query={} ue={} rb={} revision={} epoch={} "
                "counter={} age_ms={} rx_sdus={} rx_pdus={}",
                query, batch.metrics.ue_index, batch.metrics.rb_id,
                batch.revision, batch.epoch, batch.metrics.rx.counter, age,
                batch.metrics.rx.num_sdus, batch.metrics.rx.num_data_pdus);
  }

  meas_record_item_c item;
  if (snapshot.batches.empty() || pdus == 0) {
    item.set_no_value();
    logger.info("PDCP_KPM_RESULT query={} batches={} expired={} rx_sdus={} "
                "rx_pdus={} value=no_value",
                query, snapshot.batches.size(), snapshot.expired, sdus, pdus);
  } else {
    const uint32_t percent =
        static_cast<float>(sdus) / pdus * 100;
    item.set_integer() = percent;
    logger.info("PDCP_KPM_RESULT query={} batches={} expired={} rx_sdus={} "
                "rx_pdus={} value={}",
                query, snapshot.batches.size(), snapshot.expired, sdus, pdus, percent);
  }
  items.push_back(item);
  return true;
}

"""
    c += implementation
    helper = Path(__file__).with_name("pdcp-batch-history.h").read_text()
    return {
        header: h,
        source: c,
        "lib/e2/e2sm/e2sm_kpm/pdcp_batch_history.h": helper,
    }


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
    for relative, text in updated.items():
        if not args.check:
            (root / relative).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCHED'}: {relative}")
    print("Opt-in success-rate history; provider tests and runtime validation pending.")


if __name__ == "__main__":
    main()
