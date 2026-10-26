#!/usr/bin/env python3
"""Check provenance review against retained evidence and corrupted copies."""

import argparse
import copy
import csv
from datetime import datetime, timedelta
from pathlib import Path
import re
import runpy
import sys
import unittest


class ProvenanceTests(unittest.TestCase):
    evidence = None

    @classmethod
    def setUpClass(cls):
        reviewer = Path(__file__).with_name("review-pdcp-provenance.py")
        cls.review = staticmethod(runpy.run_path(str(reviewer))["review"])
        cls.log = (cls.evidence / "pdcp-provenance.log").read_text()
        with (cls.evidence / "kpm.csv").open(newline="") as stream:
            cls.rows = list(csv.DictReader(stream))

    def change_log(self, token, field, value):
        lines = self.log.splitlines()
        for i, line in enumerate(lines):
            if token + " " in line:
                lines[i], count = re.subn(
                    rf"\b{field}=\S+", f"{field}={value}", line, count=1)
                self.assertEqual(count, 1)
                return "\n".join(lines)
        self.fail(f"Missing fixture token: {token}")

    def test_retained_evidence_passes(self):
        result = self.review(self.log, self.rows)
        self.assertTrue(result["passed"])
        self.assertEqual(result["csv_rows_matched"], len(self.rows))

    def test_changed_source_payload_is_rejected(self):
        first = next(
            line for line in self.log.splitlines()
            if "PDCP_KPM_SOURCE " in line)
        value = int(re.search(r"\brx_sdus=(\d+)", first).group(1))
        log = self.change_log("PDCP_KPM_SOURCE", "rx_sdus", value + 1)
        with self.assertRaises(ValueError):
            self.review(log, self.rows)

    def test_duplicate_source_in_query_is_rejected(self):
        lines = self.log.splitlines()
        index = next(i for i, line in enumerate(lines)
                     if "PDCP_KPM_SOURCE " in line)
        lines.insert(index + 1, lines[index])
        with self.assertRaises(ValueError):
            self.review("\n".join(lines), self.rows)

    def test_expired_source_is_rejected(self):
        log = self.change_log("PDCP_KPM_SOURCE", "age_ms", 2500)
        with self.assertRaises(ValueError):
            self.review(log, self.rows)

    def test_changed_result_sum_is_rejected(self):
        first = next(line for line in self.log.splitlines()
                     if "PDCP_KPM_RESULT " in line)
        value = int(re.search(r"\brx_pdus=(\d+)", first).group(1))
        log = self.change_log("PDCP_KPM_RESULT", "rx_pdus", value + 1)
        with self.assertRaises(ValueError):
            self.review(log, self.rows)

    def test_missing_referenced_input_is_rejected(self):
        lines = self.log.splitlines()
        first = next(line for line in lines if "PDCP_KPM_SOURCE " in line)
        revision = re.search(r"\brevision=(\d+)", first).group(1)
        selected = [
            line for line in lines
            if not (
                "PDCP_BATCH_INPUT " in line
                and re.search(rf"\brevision={revision}\b", line)
            )
        ]
        self.assertEqual(len(selected), len(lines) - 1)
        with self.assertRaises(ValueError):
            self.review("\n".join(selected), self.rows)

    def test_wrong_csv_value_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        row = next(row for row in rows if row["value_type"] == "integer")
        row["value"] = str(int(row["value"]) + 1)
        with self.assertRaises(ValueError):
            self.review(self.log, rows)

    def test_unavailable_value_replaced_with_zero_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        row = next(row for row in rows if row["value_type"] == "no_value")
        row["value"] = "0"
        with self.assertRaises(ValueError):
            self.review(self.log, rows)

    def test_unmatched_csv_time_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        row = rows[0]
        end = datetime.fromisoformat(row["nominal_window_end_utc"])
        row["nominal_window_end_utc"] = (
            end + timedelta(milliseconds=500)).isoformat()
        with self.assertRaises(ValueError):
            self.review(self.log, rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    ProvenanceTests.evidence = args.evidence
    unittest.main(argv=[sys.argv[0]], verbosity=2)
