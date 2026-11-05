#!/usr/bin/env python3
"""Offline execution and reconciliation checks using simulated node outcomes."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
Coordinator = runpy.run_path(str(
    HERE / "slice_coordination_policy.py"
))["SliceCoordinator"]
Executor = runpy.run_path(str(
    HERE / "slice_coordination_executor.py"
))["CoordinatedExecutor"]


def setup_plan():
    coordinator = Coordinator()
    for revision in (1, 2):
        result = coordinator.evaluate(revision, {
            node: {
                "revision": revision,
                "receipt_time_s": revision,
                "demand_prb_percent": demand,
            }
            for node, demand in (("420", 80), ("421", 10))
        })
    return coordinator, Executor(coordinator), result["plan"]


class ExecutionChecks(unittest.TestCase):
    def test_partial_failure_then_same_plan_reconciliation(self):
        coordinator, executor, plan = setup_plan()
        calls = []

        def first(node, cap, generation):
            calls.append((node, cap, generation))
            if node == "421":
                raise ConnectionError("simulated node connection failure")
            return {"verified": True, "evidence": "simulated"}

        result = executor.execute(plan, first)
        self.assertEqual(result["status"], "reconciliation_required")
        self.assertEqual([c[0] for c in calls], ["420", "421"])
        self.assertEqual(coordinator.mode, "normal")
        self.assertEqual(coordinator.pending, plan)
        with self.assertRaisesRegex(ValueError, "execution outcome"):
            coordinator.evaluate(3, {})

        def retry(node, cap, generation):
            calls.append((node, cap, generation))
            return {"verified": True, "evidence": "simulated retry"}

        result = executor.execute(plan, retry)
        self.assertEqual(result["status"], "committed")
        self.assertEqual([c[0] for c in calls],
                         ["420", "421", "420", "421"])
        self.assertTrue(all(
            c[1]["max_prb_policy_ratio"] == 20
            and c[2] == plan["generation"] for c in calls
        ))
        self.assertEqual(coordinator.mode, "limited")
        self.assertIsNone(coordinator.pending)
        history = executor.evidence()
        self.assertEqual(len(history["attempts"]), 2)
        self.assertFalse(history["attempts"][0]["all_nodes_verified"])
        self.assertTrue(history["attempts"][1]["all_nodes_verified"])

    def test_failed_first_node_still_records_both_outcomes(self):
        coordinator, executor, plan = setup_plan()
        calls = []

        def apply(node, cap, generation):
            calls.append(node)
            return {"verified": node == "421"}

        result = executor.execute(plan, apply)
        self.assertEqual(calls, ["420", "421"])
        self.assertEqual(result["status"], "reconciliation_required")
        self.assertEqual(coordinator.mode, "normal")

    def test_changed_plan_rejected_before_callback(self):
        coordinator, executor, plan = setup_plan()
        changed = deepcopy(plan)
        changed["node_caps"]["421"]["max_prb_policy_ratio"] = 100
        calls = []
        with self.assertRaisesRegex(RuntimeError, "Plan differs"):
            executor.execute(changed, lambda *args: calls.append(args))
        self.assertEqual(calls, [])
        self.assertEqual(executor.attempts, [])
        self.assertEqual(coordinator.pending, plan)

    def test_missing_or_non_boolean_verification_cannot_commit(self):
        for outcome in ({}, {"verified": "true"}, {"verified": 1}, None):
            with self.subTest(outcome=outcome):
                coordinator, executor, plan = setup_plan()
                result = executor.execute(
                    plan, lambda *args: deepcopy(outcome)
                )
                self.assertEqual(result["status"], "reconciliation_required")
                self.assertEqual(coordinator.mode, "normal")
                self.assertIsNotNone(coordinator.pending)

    def test_completed_executor_cannot_send_again(self):
        coordinator, executor, plan = setup_plan()
        executor.execute(plan, lambda *args: {"verified": True})
        calls = []
        with self.assertRaisesRegex(RuntimeError, "already completed"):
            executor.execute(plan, lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_callback_and_evidence_copies_protect_internal_plan(self):
        coordinator, executor, plan = setup_plan()
        original = deepcopy(plan)

        def apply(node, cap, generation):
            cap["max_prb_policy_ratio"] = 99
            return {"verified": False}

        result = executor.execute(plan, apply)
        self.assertEqual(coordinator.pending, original)
        result["attempt"]["node_results"]["420"]["verified"] = True
        snapshot = executor.evidence()
        snapshot["plan"]["node_caps"]["420"]["max_prb_policy_ratio"] = 99
        self.assertEqual(executor.evidence()["plan"], original)
        self.assertFalse(
            executor.evidence()["attempts"][0]["node_results"]["420"]["verified"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
