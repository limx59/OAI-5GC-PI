#!/usr/bin/env python3
"""Offline checks for the two-node laboratory slice coordinator."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

Coordinator = runpy.run_path(str(
    Path(__file__).with_name("slice_coordination_policy.py")
))["SliceCoordinator"]


def reports(revision, now, demands=(80, 10)):
    return {
        node: {
            "revision": revision,
            "receipt_time_s": now,
            "demand_prb_percent": demand,
        }
        for node, demand in zip(("420", "421"), demands)
    }


def ready(coordinator, demands=(80, 10), start=1):
    first = coordinator.evaluate(start, reports(start, start, demands))
    if first["status"] != "pending_confirmation":
        raise AssertionError("Expected first independent confirmation")
    result = coordinator.evaluate(
        start + 1, reports(start + 1, start + 1, demands)
    )
    if result["status"] != "plan_ready":
        raise AssertionError("Expected coordinated plan")
    return result["plan"]


class PolicyChecks(unittest.TestCase):
    def test_either_node_changes_both_caps(self):
        for demands in ((80, 10), (10, 80)):
            with self.subTest(demands=demands):
                coordinator = Coordinator()
                plan = ready(coordinator, demands)
                self.assertEqual(set(plan["node_caps"]), {"420", "421"})
                for cap in plan["node_caps"].values():
                    self.assertEqual(cap, {
                        "min_prb_policy_ratio": 0,
                        "max_prb_policy_ratio": 20,
                    })
                self.assertEqual(coordinator.mode, "normal")
                coordinator.complete(
                    plan["generation"], {"420": True, "421": True}
                )
                self.assertEqual(coordinator.mode, "limited")

    def test_both_low_required_for_restoration(self):
        coordinator = Coordinator()
        plan = ready(coordinator)
        coordinator.complete(plan["generation"], {"420": True, "421": True})
        result = coordinator.evaluate(3, reports(3, 3, (10, 80)))
        self.assertEqual(result["status"], "unchanged")
        result = coordinator.evaluate(4, reports(4, 4, (10, 50)))
        self.assertEqual(result["status"], "unchanged")
        restored = ready(coordinator, (10, 10), start=5)
        self.assertEqual(restored["mode"], "normal")
        self.assertTrue(all(
            cap["max_prb_policy_ratio"] == 100
            for cap in restored["node_caps"].values()
        ))
        coordinator.complete(
            restored["generation"], {"420": True, "421": True}
        )
        self.assertEqual(coordinator.mode, "normal")

    def test_duplicate_report_cannot_confirm(self):
        coordinator = Coordinator()
        coordinator.evaluate(1, reports(1, 1))
        with self.assertRaisesRegex(ValueError, "Reused or old report"):
            coordinator.evaluate(2, reports(1, 2))
        self.assertIsNone(coordinator.pending)
        self.assertEqual(coordinator.confirmations, 1)
        self.assertEqual(coordinator.generation, 0)

    def test_missing_or_stale_report_rejected_without_state_change(self):
        for kind in ("missing", "stale"):
            with self.subTest(kind=kind):
                coordinator = Coordinator()
                value = reports(1, 10)
                if kind == "missing":
                    del value["421"]
                else:
                    value["421"]["receipt_time_s"] = 0
                previous = deepcopy(coordinator.__dict__)
                with self.assertRaises(ValueError):
                    coordinator.evaluate(10, value)
                self.assertEqual(coordinator.__dict__, previous)

    def test_partial_execution_blocks_following_plan(self):
        coordinator = Coordinator()
        plan = ready(coordinator)
        with self.assertRaisesRegex(ValueError, "reconciliation required"):
            coordinator.complete(
                plan["generation"], {"420": True, "421": False}
            )
        self.assertEqual(coordinator.mode, "normal")
        self.assertIsNotNone(coordinator.pending)
        with self.assertRaisesRegex(ValueError, "execution outcome"):
            coordinator.evaluate(3, reports(3, 3, (10, 10)))

    def test_wrong_generation_and_incomplete_outcomes_rejected(self):
        coordinator = Coordinator()
        plan = ready(coordinator)
        with self.assertRaisesRegex(ValueError, "generation"):
            coordinator.complete(
                plan["generation"] + 1, {"420": True, "421": True}
            )
        with self.assertRaisesRegex(ValueError, "both nodes"):
            coordinator.complete(plan["generation"], {"420": True})
        self.assertIsNotNone(coordinator.pending)

    def test_single_spike_does_not_produce_plan(self):
        coordinator = Coordinator()
        coordinator.evaluate(1, reports(1, 1))
        self.assertEqual(
            coordinator.evaluate(2, reports(2, 2, (10, 10)))["status"],
            "unchanged",
        )
        self.assertEqual(
            coordinator.evaluate(3, reports(3, 3))["status"],
            "pending_confirmation",
        )
        self.assertIsNone(coordinator.pending)

    def test_invalid_demand_and_time_rejected(self):
        for demand in (True, float("nan"), -1, 101):
            with self.subTest(demand=demand):
                coordinator = Coordinator()
                with self.assertRaisesRegex(ValueError, "demand"):
                    coordinator.evaluate(1, reports(1, 1, (demand, 10)))
        coordinator = Coordinator()
        coordinator.evaluate(1, reports(1, 1, (10, 10)))
        with self.assertRaisesRegex(ValueError, "decision time"):
            coordinator.evaluate(1, reports(2, 1, (10, 10)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
