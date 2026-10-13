#!/usr/bin/env python3
"""Test report silence with a deterministic clock, without the SDK."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xapp"))
from qos_report_state import ReportState

METRICS = ("DRB.UEThpDl", "DRB.UEThpUl")


def keys(node):
    return {(node, 505, 1, 0, metric) for metric in METRICS}


class ReportStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.state = ReportState(5.0, clock=lambda: self.now)
        self.all_keys = keys(1) | keys(2) | keys(3)
        self.state.register(self.all_keys)

    def test_silence_affects_only_target_node(self):
        self.now = 4.0
        self.state.observe(keys(1) | keys(3))
        self.assertEqual(self.state.expire(), [])
        self.now = 5.0
        self.assertEqual(set(self.state.expire()), keys(2))
        self.assertEqual(self.state.stale, keys(2))
        self.assertEqual(self.state.expire(), [])

    def test_recovery_and_second_silence(self):
        self.now = 5.0
        self.state.observe(keys(1) | keys(3))
        self.assertEqual(set(self.state.expire()), keys(2))
        self.now = 6.0
        self.assertEqual(set(self.state.observe(keys(2))), keys(2))
        self.assertEqual(self.state.observe(keys(2)), [])
        self.assertEqual(self.state.stale, set())
        self.now = 11.0
        self.state.observe(keys(1) | keys(3))
        self.assertEqual(set(self.state.expire()), keys(2))

    def test_first_report_timeout_and_metric_isolation(self):
        one_metric = (2, 505, 1, 0, METRICS[0])
        self.now = 4.0
        self.state.observe(keys(1) | keys(3) | {one_metric})
        self.now = 5.0
        self.assertEqual(set(self.state.expire()), keys(2) - {one_metric})
        self.assertEqual(set(self.state.observe(keys(2))),
                         keys(2) - {one_metric})

    def test_registration_does_not_reset_existing_deadline(self):
        self.now = 4.0
        self.state.register(self.all_keys)
        self.now = 5.0
        self.assertEqual(set(self.state.expire()), self.all_keys)

    def test_invalid_timeout(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ReportState(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
