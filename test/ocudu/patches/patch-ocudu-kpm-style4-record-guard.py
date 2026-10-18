#!/usr/bin/env python3
"""Guard Style 4 measurement records in a Docker source copy."""

import argparse
from pathlib import Path
import re


def patched_text(text):
    start_anchor = "bool e2sm_kpm_report_service_style4::collect_measurements()\n"
    end_anchor = "e2sm_kpm_report_service_style5::"
    if text.count(start_anchor) != 1:
        raise SystemExit("STOP: unexpected Style 4 function anchor")
    start = text.index(start_anchor)
    end = text.index(end_anchor, start)
    body = text[start:end]
    pattern = (
        r"    meas_provider\.get_meas_data\(\s*"
        r"meas_info\.meas_type, meas_info\.label_info_list, "
        r"all_matching_ues, cell_global_id, meas_records_items\);"
    )
    replacement = """    if (not meas_provider.get_meas_data(
            meas_info.meas_type, meas_info.label_info_list, all_matching_ues, cell_global_id, meas_records_items) ||
        meas_records_items.size() != all_matching_ues.size()) {
      logger.debug("Skipping Style 4 report: measurement collection failed or record count mismatched");
      clear_collect_measurements();
      return false;
    }"""
    if len(re.findall(pattern, body)) != 1:
        raise SystemExit("STOP: expected exactly one unguarded Style 4 getter")
    body = re.sub(pattern, lambda match: replacement, body, count=1)
    return text[:start] + body + text[end:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = args.source_root / "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp"
    updated = patched_text(source.read_text())
    if args.check:
        print("PASS: Style 4 guard anchor matched; no source changes")
        return
    source.write_text(updated)
    print(f"Patched: {source}")


if __name__ == "__main__":
    main()
