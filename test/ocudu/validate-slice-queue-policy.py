#!/usr/bin/env python3
"""Offline checks for laboratory post-grant queue recommendations."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

Policy = runpy.run_path(str(
    Path(__file__).with_name("slice_queue_policy.py")
))["QueuePolicy"]
SOURCES = {"420": "instance-420", "421": "instance-421"}


def reports(revision, values=(32768, 0)):
    end = revision * 2
    result = {}
    for node, value in zip(SOURCES, values):
        samples = [] if value is None else [
            {"pending_dl_bytes_after_grant": value}
        ]
        result[node] = {
            "node_id": node,
            "source_instance": SOURCES[node],
            "revision": revision,
            "host_query_start_s": end - 1,
            "host_query_end_s": end,
            "queue_unit": "bytes",
            "prb_demand_percent_established": False,
            "samples": samples,
            "sample_count": len(samples),
            "observation_status": "unknown" if value is None else "observed",
            "queue_statistics": None if value is None else {
                "minimum": value, "maximum": value,
                "positive_samples": int(value > 0),
            },
        }
    return result


class QueueChecks(unittest.TestCase):
    def test_either_high_requires_two_fresh_pairs(self):
        for values in ((32768, 0), (0, 32768)):
            with self.subTest(values=values):
                policy = Policy(SOURCES)
                first = policy.evaluate(2, reports(1, values))
                self.assertEqual(first["status"], "pending_confirmation")
                self.assertIsNone(first["recommended_max_ratio"])
                second = policy.evaluate(4, reports(2, values))
                self.assertEqual(second["status"], "confirmed")
                self.assertEqual(second["recommended_max_ratio"], 20)

    def test_both_low_boundary_confirms_restoration(self):
        policy = Policy(SOURCES)
        policy.evaluate(2, reports(1, (1024, 0)))
        result = policy.evaluate(4, reports(2, (0, 1024)))
        self.assertEqual(result["recommended_max_ratio"], 100)

    def test_unknown_blocks_joint_recommendation_and_resets(self):
        policy = Policy(SOURCES)
        policy.evaluate(2, reports(1))
        held = policy.evaluate(4, reports(2, (32768, None)))
        self.assertEqual(held["status"], "hold")
        self.assertEqual(held["confirmations"], 0)
        next_result = policy.evaluate(6, reports(3))
        self.assertEqual(next_result["status"], "pending_confirmation")

    def test_middle_band_resets_confirmation(self):
        policy = Policy(SOURCES)
        policy.evaluate(2, reports(1))
        self.assertEqual(
            policy.evaluate(4, reports(2, (32767, 0)))["status"], "hold"
        )
        self.assertEqual(
            policy.evaluate(6, reports(3))["status"], "pending_confirmation"
        )

    def test_candidate_change_requires_new_confirmation(self):
        policy = Policy(SOURCES)
        policy.evaluate(2, reports(1))
        result = policy.evaluate(4, reports(2, (0, 0)))
        self.assertEqual(result["candidate"], "normal")
        self.assertEqual(result["confirmations"], 1)
        self.assertIsNone(result["recommended_max_ratio"])

    def test_duplicate_and_overlap_rejected_without_state_change(self):
        policy = Policy(SOURCES)
        policy.evaluate(2, reports(1))
        for kind in ("duplicate", "overlap"):
            bad = reports(1 if kind == "duplicate" else 2)
            if kind == "overlap":
                bad["421"]["host_query_start_s"] = 1
            before = deepcopy(policy.__dict__)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                policy.evaluate(4, bad)
            self.assertEqual(policy.__dict__, before)

    def test_invalid_reports_rejected_atomically(self):
        for kind in (
            "missing", "source", "stale", "future", "count",
            "statistics", "boolean_bytes", "status", "units", "revision",
        ):
            policy = Policy(SOURCES)
            policy.evaluate(2, reports(1))
            bad = reports(2)
            now = 4
            if kind == "missing":
                del bad["421"]
            elif kind == "source":
                bad["421"]["source_instance"] = "restarted"
            elif kind == "stale":
                now = 12
            elif kind == "future":
                bad["421"]["host_query_end_s"] = 5
            elif kind == "count":
                bad["421"]["sample_count"] = 2
            elif kind == "statistics":
                bad["421"]["queue_statistics"]["maximum"] = 99
            elif kind == "boolean_bytes":
                bad["421"]["samples"][0]["pending_dl_bytes_after_grant"] = True
            elif kind == "status":
                bad["421"]["observation_status"] = "unknown"
            elif kind == "units":
                bad["421"]["queue_unit"] = "percent"
            else:
                bad["421"]["revision"] = True
            before = deepcopy(policy.__dict__)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                policy.evaluate(now, bad)
            self.assertEqual(policy.__dict__, before)

    def test_backward_time_rejected(self):
        policy = Policy(SOURCES)
        policy.evaluate(2, reports(1))
        before = deepcopy(policy.__dict__)
        with self.assertRaises(ValueError):
            policy.evaluate(1, reports(2))
        self.assertEqual(policy.__dict__, before)

    def test_source_mapping_copied_and_no_execution_claim(self):
        sources = deepcopy(SOURCES)
        policy = Policy(sources)
        sources["420"] = "changed"
        policy.evaluate(2, reports(1))
        result = policy.evaluate(4, reports(2))
        self.assertEqual(result["control_requests_sent"], 0)
        self.assertIs(result["scheduler_execution_validated"], False)
        self.assertIs(result["source_collection_time_validated"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
