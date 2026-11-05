#!/usr/bin/env python3
"""Offline queue-control state and executor compatibility checks."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
State = runpy.run_path(str(
    HERE / "slice_queue_control_state.py"
))["QueueControlState"]
Executor = runpy.run_path(str(
    HERE / "slice_coordination_executor.py"
))["CoordinatedExecutor"]


def confirmed(ratio):
    return {
        "status": "confirmed",
        "candidate": "limited" if ratio == 20 else "normal",
        "confirmations": 2,
        "recommended_max_ratio": ratio,
    }


class StateChecks(unittest.TestCase):
    def test_initial_state_and_unconfirmed_decisions_send_nothing(self):
        state = State(100)
        self.assertIsNone(state.propose(1, {
            "status": "pending_confirmation",
            "recommended_max_ratio": None,
        }))
        self.assertIsNone(state.propose(2, {
            "status": "hold", "recommended_max_ratio": None,
        }))
        self.assertIsNone(state.propose(3, confirmed(100)))
        self.assertEqual(state.generation, 0)
        self.assertEqual(state.max_ratio, 100)

    def test_executor_commit_restore_and_deduplication(self):
        state = State(100)
        calls = []

        def apply(node, cap, generation):
            calls.append((node, cap["max_prb_policy_ratio"], generation))
            return {"verified": True}

        for revision, ratio in ((1, 20), (2, 100)):
            plan = state.propose(revision, confirmed(ratio))
            Executor(state).execute(plan, apply)
            self.assertIsNone(state.pending)
            self.assertEqual(state.max_ratio, ratio)
        self.assertIsNone(state.propose(3, confirmed(100)))
        self.assertEqual(calls, [
            ("420", 20, 1), ("421", 20, 1),
            ("420", 100, 2), ("421", 100, 2),
        ])

    def test_partial_failure_blocks_new_plan_and_retry_reconciles(self):
        state = State(100)
        plan = state.propose(1, confirmed(20))
        executor = Executor(state)
        calls = []

        def partial(node, cap, generation):
            calls.append(node)
            return {"verified": node == "420"}

        executor.execute(plan, partial)
        self.assertEqual(calls, ["420", "421"])
        self.assertEqual(state.max_ratio, 100)
        self.assertEqual(state.generation, 0)
        self.assertEqual(state.pending, plan)
        before = deepcopy(state.__dict__)
        with self.assertRaises(ValueError):
            state.propose(2, confirmed(100))
        self.assertEqual(state.__dict__, before)
        executor.execute(plan, lambda *args: {"verified": True})
        self.assertEqual(state.max_ratio, 20)
        self.assertIsNone(state.pending)

    def test_invalid_completion_preserves_pending_state(self):
        for generation, outcomes in (
            (2, {"420": True, "421": True}),
            (1, {"420": True}),
            (1, {"420": True, "421": 1}),
            (1, {"420": True, "421": False}),
        ):
            state = State(100)
            state.propose(1, confirmed(20))
            before = deepcopy(state.__dict__)
            with self.subTest(outcomes=outcomes), self.assertRaises(ValueError):
                state.complete(generation, outcomes)
            self.assertEqual(state.__dict__, before)

    def test_duplicate_revision_and_invalid_confirmation_rejected(self):
        state = State(100)
        state.propose(1, confirmed(100))
        before = deepcopy(state.__dict__)
        with self.assertRaises(ValueError):
            state.propose(1, confirmed(20))
        self.assertEqual(state.__dict__, before)
        for change in (
            {"confirmations": 1},
            {"recommended_max_ratio": True},
            {"candidate": "normal"},
        ):
            decision = confirmed(20)
            decision.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                state.propose(2, decision)
            self.assertEqual(state.__dict__, before)

    def test_returned_plan_cannot_mutate_internal_state(self):
        state = State(100)
        plan = state.propose(1, confirmed(20))
        plan["node_caps"]["420"]["max_prb_policy_ratio"] = 100
        self.assertEqual(
            state.pending["node_caps"]["420"]["max_prb_policy_ratio"], 20
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
