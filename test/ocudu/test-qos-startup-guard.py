#!/usr/bin/env python3
"""Exercise readiness recovery and fail-closed timeout without containers."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import qos_startup_guard as guard


class StartupGuardTests(unittest.TestCase):
    def exercise(self, snapshots, seconds):
        now = [0.0]
        clock = SimpleNamespace(
            monotonic=lambda: now[0],
            sleep=lambda duration: now.__setitem__(0, now[0] + duration),
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "readiness.json"
            with patch.object(guard, "snapshot", side_effect=snapshots), \
                 patch.object(guard, "time", clock):
                try:
                    result = guard.wait_host_ready(
                        output, stable_samples=3, max_seconds=seconds,
                    )
                    error = None
                except RuntimeError as failure:
                    result = None
                    error = failure
            saved = json.loads(output.read_text())
        return result, saved, error

    def test_ready_after_three_samples(self):
        result, saved, error = self.exercise(
            [(0, 0, 0), (100, 0, 0), (200, 0, 0), (300, 0, 0)], 4,
        )
        self.assertIsNone(error)
        self.assertTrue(result["passed"])
        self.assertTrue(saved["passed"])
        self.assertEqual(len(saved["samples"]), 3)

    def test_io_spike_resets_readiness_streak(self):
        result, saved, error = self.exercise(
            [
                (0, 0, 0), (100, 0, 0), (200, 60, 0),
                (300, 60, 0), (400, 60, 0), (500, 60, 0),
            ], 6,
        )
        self.assertIsNone(error)
        self.assertTrue(result["passed"])
        self.assertEqual(
            [row["ready_streak"] for row in saved["samples"]],
            [1, 0, 1, 2, 3],
        )

    def test_blocked_tasks_timeout_preserves_failed_evidence(self):
        result, saved, error = self.exercise(
            [(0, 0, 0)] + [(i * 100, 0, 16) for i in range(1, 5)], 4,
        )
        self.assertIsNone(result)
        self.assertIsInstance(error, RuntimeError)
        self.assertFalse(saved["passed"])
        self.assertEqual(len(saved["samples"]), 4)
        self.assertTrue(all(
            row["ready_streak"] == 0 for row in saved["samples"]
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
