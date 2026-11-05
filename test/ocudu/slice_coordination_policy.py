#!/usr/bin/env python3
"""Plan coordinated lab slice caps from two explicit demand reports.

Demand is an input estimate, not measured PRB utilisation.
A common cap is applied independently in each cell.
This module neither sends controls nor establishes scheduler execution.
"""
import math


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value))


class SliceCoordinator:
    def __init__(self, nodes=("420", "421"), max_age_s=7):
        require(len(nodes) == 2 and len(set(nodes)) == 2
                and all(isinstance(n, str) and n for n in nodes),
                "Expected two distinct node IDs")
        require(number(max_age_s) and max_age_s > 0,
                "Invalid report age limit")
        self.nodes = tuple(nodes)
        self.max_age_s = max_age_s
        self.revisions = {}
        self.last_time = None
        self.mode = "normal"
        self.candidate = None
        self.confirmations = 0
        self.generation = 0
        self.pending = None

    def evaluate(self, now_s, reports):
        require(self.pending is None,
                "Previous plan requires execution outcome")
        require(number(now_s) and now_s >= 0
                and (self.last_time is None or now_s > self.last_time),
                "Invalid or non-increasing decision time")
        require(isinstance(reports, dict)
                and set(reports) == set(self.nodes),
                "Expected reports from both configured nodes")

        revisions = {}
        demands = {}
        for node in self.nodes:
            item = reports[node]
            require(isinstance(item, dict), "Invalid report: " + node)
            revision = item.get("revision")
            receipt = item.get("receipt_time_s")
            demand = item.get("demand_prb_percent")
            require(type(revision) is int
                    and revision > self.revisions.get(node, 0),
                    "Reused or old report: " + node)
            require(number(receipt) and 0 <= receipt <= now_s
                    and now_s - receipt <= self.max_age_s,
                    "Invalid or stale report time: " + node)
            require(number(demand) and 0 <= demand <= 100,
                    "Invalid demand estimate: " + node)
            revisions[node] = revision
            demands[node] = demand

        # Commit input state only after validating the complete report pair.
        self.last_time = now_s
        self.revisions = revisions
        if max(demands.values()) >= 70:
            requested = "limited"
        elif max(demands.values()) <= 30:
            requested = "normal"
        else:
            requested = self.mode

        if requested == self.mode:
            self.candidate = None
            self.confirmations = 0
            return {
                "status": "unchanged", "mode": self.mode,
                "control_requests_sent": 0,
            }

        self.confirmations = (
            self.confirmations + 1 if requested == self.candidate else 1
        )
        self.candidate = requested
        if self.confirmations < 2:
            return {
                "status": "pending_confirmation",
                "candidate": requested,
                "independent_pairs": self.confirmations,
                "control_requests_sent": 0,
            }

        self.generation += 1
        ratio = 20 if requested == "limited" else 100
        plan = {
            "generation": self.generation,
            "mode": requested,
            "input_revisions": dict(revisions),
            "demand_estimates": dict(demands),
            "node_caps": {
                node: {
                    "min_prb_policy_ratio": 0,
                    "max_prb_policy_ratio": ratio,
                } for node in self.nodes
            },
        }
        self.pending = plan
        return {
            "status": "plan_ready",
            "plan": {
                **plan,
                "node_caps": {
                    node: dict(cap) for node, cap in plan["node_caps"].items()
                },
            },
            "control_requests_sent": 0,
            "scheduler_execution_validated": False,
        }

    def complete(self, generation, node_results):
        require(self.pending is not None
                and type(generation) is int
                and generation == self.pending["generation"],
                "Unexpected execution generation")
        require(isinstance(node_results, dict)
                and set(node_results) == set(self.nodes)
                and all(type(v) is bool for v in node_results.values()),
                "Expected explicit outcomes for both nodes")
        require(all(node_results.values()),
                "Partial or failed execution; reconciliation required")
        self.mode = self.pending["mode"]
        self.pending = None
        self.candidate = None
        self.confirmations = 0
        return {
            "status": "committed",
            "generation": generation,
            "mode": self.mode,
        }
