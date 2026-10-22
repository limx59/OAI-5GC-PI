#!/usr/bin/env python3
"""Offline behavioral checks for the OCUDU advisory QoS state."""

import unittest

from qos_monitor_state import MonitorState, normalize

DL = "DRB.UEThpDl"
UL = "DRB.UEThpUl"
DELAY = "DRB.RlcSduDelayDl"
DROP = "DRB.RlcPacketDropRateDl"


class QoSStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.monitor = MonitorState(clock=lambda: self.now)
        self.monitor.reconnect()
        self.monitor.register(420, 0, (DL, UL, DELAY, DROP))

    def feed(self, sequence, value, metric=DL, **kwargs):
        return self.monitor.observe(
            self.monitor.generation, 420, 0, metric,
            sequence, value, **kwargs,
        )

    def labels(self, events):
        return [event["event"] for event in events]

    def test_units(self):
        self.assertEqual(normalize(DL, 1000), 1000000)
        self.assertEqual(normalize(UL, 250), 250000)
        self.assertEqual(normalize(DELAY, 125), 12.5)
        self.assertEqual(normalize("DRB.RlcDelayUl", 20), 2)
        self.assertEqual(normalize(DROP, 5), 5)

    def test_invalid_values(self):
        for value in (-1, float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize(DL, value)
        with self.assertRaises(ValueError):
            normalize(DROP, 101)

    def test_sustained_alert_without_repeated_alerts(self):
        self.assertNotIn("ALERT", self.labels(self.feed(1, 200)))
        self.assertNotIn("ALERT", self.labels(self.feed(2, 200)))
        events = self.feed(3, 200)
        self.assertEqual(self.labels(events), ["ALERT"])
        self.assertEqual(events[0]["consecutive"], 3)
        self.assertEqual(events[0]["value"], 200000)
        self.assertEqual(events[0]["mode"], "advisory")
        self.assertEqual(self.feed(4, 200), [])

    def test_hysteresis_and_consecutive_recovery(self):
        for sequence in range(1, 4):
            self.feed(sequence, 200)
        self.assertEqual(self.feed(4, 700), [])
        self.assertEqual(self.feed(5, 800), [])
        self.assertEqual(self.feed(6, 800), [])
        self.assertEqual(self.feed(7, 700), [])
        self.assertEqual(self.feed(8, 800), [])
        self.assertEqual(self.feed(9, 800), [])
        self.assertEqual(self.labels(self.feed(10, 800)), ["RECOVERY"])

    def test_healthy_report_breaks_low_streak(self):
        self.feed(1, 200)
        self.feed(2, 200)
        self.feed(3, 1000)
        self.assertNotIn("ALERT", self.labels(self.feed(4, 200)))
        self.assertNotIn("ALERT", self.labels(self.feed(5, 200)))
        self.assertEqual(self.labels(self.feed(6, 200)), ["ALERT"])

    def test_high_delay_and_drop_thresholds(self):
        for metric, raw in ((DELAY, 510), (DROP, 6)):
            for sequence in (1, 2):
                self.assertNotIn(
                    "ALERT", self.labels(self.feed(sequence, raw, metric))
                )
            self.assertEqual(
                self.labels(self.feed(3, raw, metric)), ["ALERT"]
            )

    def test_missing_and_incomplete_break_streak(self):
        for missing in (False, True):
            self.setUp()
            self.feed(1, 200)
            self.feed(2, 200)
            self.feed(3, 200 if missing else None, incomplete=missing)
            self.assertNotIn("ALERT", self.labels(self.feed(4, 200)))
            self.assertNotIn("ALERT", self.labels(self.feed(5, 200)))
            self.assertEqual(self.labels(self.feed(6, 200)), ["ALERT"])

    def test_missing_clears_active_alert_to_unknown(self):
        for sequence in (1, 2, 3):
            self.feed(sequence, 200)
        self.assertEqual(self.labels(self.feed(4, None)), ["UNKNOWN"])
        self.assertEqual(self.feed(5, None), [])
        events = self.feed(6, 1000)
        self.assertEqual(self.labels(events), ["REPORT_RESUMED"])

    def test_first_report_silence_and_recovery(self):
        self.now = 4.999
        self.assertEqual(self.monitor.expire(), [])
        self.now = 5
        expired = self.monitor.expire()
        self.assertEqual(len(expired), 4)
        self.assertTrue(all(e["event"] == "STALE" for e in expired))
        self.assertEqual(self.monitor.expire(), [])
        self.assertEqual(
            self.labels(self.feed(1, 1000)), ["REPORT_RESUMED"]
        )

    def test_missing_does_not_refresh_valid_data_deadline(self):
        self.feed(1, 1000)
        self.now = 4
        self.feed(2, None)
        self.now = 5
        events = self.monitor.expire()
        self.assertTrue(any(
            e["metric"] == DL and e["event"] == "STALE" for e in events
        ))

    def test_duplicate_reports_do_not_advance_alert(self):
        self.feed(1, 200)
        self.assertEqual(self.feed(1, 200), [])
        self.assertEqual(self.feed(0, 200), [])
        self.assertNotIn("ALERT", self.labels(self.feed(2, 200)))
        self.assertEqual(self.labels(self.feed(3, 200)), ["ALERT"])

    def test_reconnect_drops_old_generation_and_counters(self):
        self.feed(1, 200)
        self.feed(2, 200)
        old = self.monitor.generation
        reset = self.monitor.reconnect()
        self.assertEqual(reset["generation"], old + 1)
        self.monitor.register(420, 0, (DL,))
        self.assertEqual(
            self.monitor.observe(old, 420, 0, DL, 99, 200), []
        )
        self.assertNotIn("ALERT", self.labels(self.feed(1, 200)))
        self.assertNotIn("ALERT", self.labels(self.feed(2, 200)))
        self.assertEqual(self.labels(self.feed(3, 200)), ["ALERT"])

    def test_node_ue_and_metric_isolation(self):
        self.monitor.register(421, 0, (DL,))
        self.monitor.register(420, 1, (DL,))
        for sequence in (1, 2, 3):
            self.feed(sequence, 200)
            self.monitor.observe(
                self.monitor.generation, 421, 0, DL, sequence, 1000
            )
            self.monitor.observe(
                self.monitor.generation, 420, 1, DL, sequence, 1000
            )
            self.feed(sequence, 1000, UL)
        self.assertEqual(self.monitor.states[(420, 0, DL)]["status"], "ALERT")
        for key in ((421, 0, DL), (420, 1, DL), (420, 0, UL)):
            self.assertEqual(self.monitor.states[key]["status"], "HEALTHY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
