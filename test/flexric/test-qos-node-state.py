#!/usr/bin/env python3
"""Test QoS node state with synthetic indications, without the native SDK."""

from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

XAPP = Path(__file__).resolve().parents[1] / "xapp"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, XAPP / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CallbackBase:
    pass


# Substitute only the SDK-facing demo module. Use the real recorder and QoS.
ric = NS(FORMAT_1_INDICATION_MESSAGE=1, FORMAT_3_INDICATION_MESSAGE=3,
         NAME_MEAS_TYPE=1, INTEGER_MEAS_VALUE=1, REAL_MEAS_VALUE=2,
         TRUE_ENUM_VALUE=1)
demo = NS(KPMCallback=CallbackBase, ric=ric, sys=sys)
with patch.dict(sys.modules, {"xapp_kpm": demo}):
    recorder = load("recorder_under_test", "xapp_kpm_recorder.py")
    with patch.dict(sys.modules, {"xapp_kpm_recorder": recorder}), \
         patch.dict(os.environ, XAPP_QOS_THRESHOLD="10", XAPP_QOS_LOW_REPORTS="2"):
        qos = load("qos_under_test", "xapp_qos_watch.py")

METRICS = ("DRB.UEThpDl", "DRB.UEThpUl")


def indication(node, value=1.0, empty=False):
    info = [NS(meas_type=NS(type=1, name=metric)) for metric in METRICS]
    values = [NS(value=2, real_val=value) for _ in METRICS]
    row = NS(meas_record_len=2, meas_record_lst=values, incomplete_flag=0)
    report = NS(meas_data_lst=[] if empty else [row],
                meas_info_lst_len=2, meas_info_lst=info)
    return NS(id=NS(nb_id=NS(nb_id=node), plmn=NS(mcc=505, mnc=1), type=0),
              msg=NS(type=1, frm_1=report))


def key(node, metric):
    return (node, 505, 1, 0, metric)


class NodeStateTests(unittest.TestCase):
    def setUp(self):
        self.callback = qos.QoSCallback()
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def send(self, node, value=1.0, empty=False):
        self.callback.record(indication(node, value, empty))

    def alert_all(self):
        for _ in range(2):
            for node in (1, 2, 3):
                self.send(node)

    def test_interleaved_nodes_alert_independently(self):
        self.alert_all()
        expected = {key(node, metric)
                    for node in (1, 2, 3) for metric in METRICS}
        self.assertEqual(self.callback.alerts, expected)
        self.assertEqual(self.output.getvalue().count("ALERT:"), 6)
        for node in (1, 2, 3):
            self.send(node)
        self.assertEqual(self.output.getvalue().count("ALERT:"), 6)
        self.assertTrue(all(self.callback.low_counts[k] == 3 for k in expected))

    def test_missing_data_resets_only_reporting_node(self):
        self.alert_all()
        self.send(1, empty=True)
        for metric in METRICS:
            self.assertEqual(self.callback.low_counts[key(1, metric)], 0)
            self.assertNotIn(key(1, metric), self.callback.alerts)
            for node in (2, 3):
                self.assertEqual(self.callback.low_counts[key(node, metric)], 2)
                self.assertIn(key(node, metric), self.callback.alerts)
        self.assertEqual(self.output.getvalue().count("UNKNOWN:"), 2)
        self.send(1)
        self.assertEqual(self.output.getvalue().count("ALERT:"), 6)
        self.send(1)
        self.assertEqual(self.output.getvalue().count("ALERT:"), 8)

    def test_recovery_changes_only_reporting_node(self):
        self.alert_all()
        self.send(1, value=10.0)
        for metric in METRICS:
            self.assertEqual(self.callback.low_counts[key(1, metric)], 0)
            self.assertNotIn(key(1, metric), self.callback.alerts)
            for node in (2, 3):
                self.assertEqual(self.callback.low_counts[key(node, metric)], 2)
                self.assertIn(key(node, metric), self.callback.alerts)
        self.assertEqual(self.output.getvalue().count("RECOVERY:"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
