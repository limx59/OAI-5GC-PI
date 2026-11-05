#!/usr/bin/env python3
"""Check reusable energy recommendations and simulated state transitions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/xapp"))
from xapp_energy_policy import EnergyPolicy
from xapp_energy_simulator import simulate


def sample(timestamp, **changes):
    value = {
        "time_s": timestamp, "demand_ratio": 0.1,
        "observed_mode": "active", "active_ues": 0,
        "neighbor_coverage_confirmed": True,
    }
    value.update(changes)
    return value


class EnergyChecks(unittest.TestCase):
    def test_existing_advisory_and_simulation_cycle(self):
        samples = json.loads(
            (ROOT / "test/xapp/energy_samples.json").read_text()
        )
        original = deepcopy(samples)
        policy = EnergyPolicy()
        advice = [policy.evaluate(item) for item in samples]
        self.assertEqual([r["status"] for r in advice], [
            "pending", "pending", "pending", "recommendation",
            "hold_energy_saving", "recommendation",
        ])
        self.assertEqual(advice[3]["action"], "consider_energy_saving")
        self.assertEqual(advice[5]["action"], "restore_active_mode")
        events = simulate(samples)
        self.assertEqual([
            (e["time_s"], e["simulation_mode_before"],
             e["simulation_mode_after"])
            for e in events if e["applied_in_simulation"]
        ], [(30, "active", "energy_saving"),
            (50, "energy_saving", "active")])
        self.assertTrue(all(e["executed"] is False for e in advice + events))
        self.assertEqual(samples, original)

    def test_entry_requires_full_low_demand_duration(self):
        policy = EnergyPolicy()
        for timestamp in (0, 10, 20, 29):
            self.assertEqual(policy.evaluate(
                sample(timestamp, demand_ratio=0.2)
            )["status"], "pending")
        self.assertEqual(
            policy.evaluate(sample(30, demand_ratio=0.2))["action"],
            "consider_energy_saving",
        )

    def test_users_coverage_or_high_demand_block_entry(self):
        for changes in (
            {"active_ues": 1},
            {"neighbor_coverage_confirmed": False},
            {"demand_ratio": 0.21},
        ):
            with self.subTest(changes=changes):
                policy = EnergyPolicy()
                policy.evaluate(sample(0))
                result = policy.evaluate(sample(10, **changes))
                self.assertEqual(result["status"], "hold_active")
                self.assertEqual(policy.evaluate(sample(20))["status"], "pending")
                self.assertEqual(policy.low_since, 20)

    def test_report_gap_resets_low_demand_duration(self):
        policy = EnergyPolicy()
        policy.evaluate(sample(0))
        policy.evaluate(sample(10))
        result = policy.evaluate(sample(30))
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["low_demand_duration_s"], 0)

    def test_restore_for_demand_users_or_coverage_loss(self):
        for changes in (
            {"demand_ratio": 0.6},
            {"active_ues": 1},
            {"neighbor_coverage_confirmed": False},
        ):
            with self.subTest(changes=changes):
                result = EnergyPolicy().evaluate(sample(
                    0, observed_mode="energy_saving", **changes
                ))
                self.assertEqual(result["action"], "restore_active_mode")
                self.assertIs(result["executed"], False)

    def test_duplicate_or_backward_time_rejected(self):
        policy = EnergyPolicy()
        policy.evaluate(sample(10))
        for timestamp in (10, 9):
            with self.assertRaises(ValueError):
                policy.evaluate(sample(timestamp))

    def test_invalid_observations_rejected(self):
        for changes in (
            {"time_s": float("nan")},
            {"demand_ratio": float("inf")},
            {"demand_ratio": -0.1},
            {"observed_mode": "off"},
            {"active_ues": True},
            {"neighbor_coverage_confirmed": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                EnergyPolicy().evaluate(sample(0, **changes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
