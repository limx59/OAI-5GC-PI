#!/usr/bin/env python3
"""Track acknowledged lab cap state for live queue recommendations.

Compatible with CoordinatedExecutor. Initial 100% state must be verified
from the caller's configuration. This module sends no controls.
Cross-node execution is sequential, not atomic; state is not persistent.
"""
from copy import deepcopy


def require(condition, message):
    if not condition:
        raise ValueError(message)


class QueueControlState:
    def __init__(self, initial_max_ratio):
        require(type(initial_max_ratio) is int and initial_max_ratio == 100,
                "Expected verified initial 100-percent configuration")
        self.nodes = ("420", "421")
        self.max_ratio = initial_max_ratio
        self.mode = "normal"
        self.generation = 0
        self.last_revision = 0
        self.pending = None

    def propose(self, revision, decision):
        require(self.pending is None,
                "Pending execution must be reconciled before new plans")
        require(type(revision) is int and revision > self.last_revision,
                "Duplicate or invalid decision revision")
        require(isinstance(decision, dict), "Invalid queue decision")
        status = decision.get("status")
        require(status in ("hold", "pending_confirmation", "confirmed"),
                "Unexpected decision status")
        ratio = decision.get("recommended_max_ratio")
        if status != "confirmed":
            require(ratio is None, "Unconfirmed recommendation contains cap")
            self.last_revision = revision
            return None

        require(type(ratio) is int and ratio in (20, 100)
                and decision.get("candidate") ==
                    ("limited" if ratio == 20 else "normal")
                and type(decision.get("confirmations")) is int
                and decision["confirmations"] >= 2,
                "Invalid confirmed recommendation")
        self.last_revision = revision
        if ratio == self.max_ratio:
            return None

        self.pending = {
            "generation": self.generation + 1,
            "mode": "limited" if ratio == 20 else "normal",
            "decision_revision": revision,
            "basis": "live post-grant queue-byte recommendation",
            "node_caps": {
                node: {
                    "min_prb_policy_ratio": 0,
                    "max_prb_policy_ratio": ratio,
                }
                for node in self.nodes
            },
        }
        return deepcopy(self.pending)

    def complete(self, generation, node_results):
        require(self.pending is not None, "No pending execution")
        require(type(generation) is int
                and generation == self.pending["generation"],
                "Execution generation mismatch")
        require(isinstance(node_results, dict)
                and set(node_results) == set(self.nodes)
                and all(type(v) is bool for v in node_results.values()),
                "Both explicit node outcomes required")
        require(all(node_results.values()),
                "Partial or failed execution; reconciliation required")
        self.generation = generation
        self.mode = self.pending["mode"]
        self.max_ratio = self.pending["node_caps"]["420"]["max_prb_policy_ratio"]
        self.pending = None
        return {
            "status": "committed",
            "generation": self.generation,
            "mode": self.mode,
        }
