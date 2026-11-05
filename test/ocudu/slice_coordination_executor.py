#!/usr/bin/env python3
"""Execute and reconcile one pending dual-node laboratory cap plan.

The callback must apply an absolute cap and verify the node outcome.
Retries reapply the same plan to both nodes. Cross-node updates are
sequential and are not atomic. State persistence is owned by the caller.
"""
from copy import deepcopy


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class CoordinatedExecutor:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.plan = None
        self.attempts = []
        self.completed = False

    def execute(self, plan, apply_and_verify):
        require(callable(apply_and_verify), "Expected execution callback")
        require(not self.completed, "Executor already completed")
        require(self.coordinator.pending is not None,
                "Coordinator has no pending plan")
        require(plan == self.coordinator.pending,
                "Plan differs from coordinator pending state")
        if self.plan is None:
            self.plan = deepcopy(plan)
        require(plan == self.plan, "Cannot change a plan during recovery")

        results = {}
        for node in self.coordinator.nodes:
            try:
                value = apply_and_verify(
                    node, deepcopy(self.plan["node_caps"][node]),
                    self.plan["generation"],
                )
                require(isinstance(value, dict),
                        "Node callback must return an evidence object")
                require(type(value.get("verified")) is bool,
                        "Node outcome must contain explicit verified flag")
                results[node] = deepcopy(value)
            except Exception as error:
                results[node] = {
                    "verified": False,
                    "error": str(error),
                    "state_may_have_changed": True,
                }

        attempt = {
            "attempt": len(self.attempts) + 1,
            "generation": self.plan["generation"],
            "node_results": results,
            "all_nodes_verified": all(
                value["verified"] for value in results.values()
            ),
        }
        self.attempts.append(deepcopy(attempt))
        if not attempt["all_nodes_verified"]:
            require(self.coordinator.pending == self.plan,
                    "Pending state changed during failed execution")
            return {
                "status": "reconciliation_required",
                "attempt": deepcopy(attempt),
                "new_plans_blocked": True,
            }

        committed = self.coordinator.complete(
            self.plan["generation"],
            {node: True for node in self.coordinator.nodes},
        )
        self.completed = True
        return {
            "status": "committed",
            "attempt": deepcopy(attempt),
            "coordinator_result": committed,
        }

    def evidence(self):
        return deepcopy({
            "plan": self.plan,
            "attempts": self.attempts,
            "completed": self.completed,
            "atomic_cross_node_update": False,
            "persistent_recovery_validated": False,
        })
