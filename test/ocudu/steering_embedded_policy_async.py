"""Configurable embedded-lab advisory policy; no control execution."""
import math

class EmbeddedSteeringPolicy:
    def __init__(self, config):
        self.policy = config["policy"]
        self.checks = config["input_checks"]
        if config.get("observation_mode") != "asynchronous_latest_unused_sources":
            raise ValueError("Expected explicit asynchronous laboratory mode")
        if self.checks.get("require_source_receipt_alignment") is not False:
            raise ValueError("Async mode must explicitly disable receipt alignment")
        if self.checks.get("max_source_receipt_skew_seconds") is not None:
            raise ValueError("Async mode must use no source receipt-skew limit")
        if config.get("control_execution_enabled") is not False:
            raise ValueError("Only advisory mode is supported")
        for name in ("source_load_min", "target_load_max",
                     "load_difference_min"):
            value = self.policy[name]
            if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Invalid policy threshold: " + name)
        count = self.policy["consecutive_independent_pairs"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 2:
            raise ValueError("Expected at least two independent pairs")
        for value in (
            self.policy["cooldown_seconds"],
            self.checks["max_receipt_age_seconds"],
            self.checks["max_query_skew_seconds"],
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid timing limit")
        if self.checks.get("deduplicate_source_batches") is not True:
            raise ValueError("Source deduplication is required")
        self.last_time = None
        self.last_recommendation = None
        self.last_revision = {}
        self.nodes = None
        self.candidate = None
        self.consecutive = 0

    def reject(self, reason):
        self.candidate = None
        self.consecutive = 0
        return {"status": "input_rejected", "reason": reason,
                "control_executed": False}

    def evaluate(self, time_s, observations):
        # Each observation uses seconds in the same host monotonic clock.
        if isinstance(time_s, bool) or not math.isfinite(time_s) or time_s < 0:
            return self.reject("invalid_time")
        if self.last_time is not None and time_s <= self.last_time:
            return self.reject("non_increasing_time")
        self.last_time = time_s
        if not isinstance(observations, dict) or len(observations) != 2:
            return self.reject("expected_two_nodes")
        nodes = frozenset(observations)
        if any(not isinstance(node, str) or not node for node in nodes):
            return self.reject("invalid_node")
        if self.nodes is not None and nodes != self.nodes:
            return self.reject("node_set_changed")

        for node, item in observations.items():
            revision = item.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
                return self.reject("invalid_revision")
            if revision <= self.last_revision.get(node, 0):
                return self.reject("reused_or_old_source")
            values = [item.get(name) for name in
                      ("load", "query_time_s", "receipt_time_s")]
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in values):
                return self.reject("invalid_measurement")
            load, query, receipt = values
            if not 0 <= load <= 1 or not 0 <= receipt <= query <= time_s:
                return self.reject("invalid_value_or_time_order")
            if time_s - receipt > self.checks["max_receipt_age_seconds"]:
                return self.reject("source_receipt_too_old")

        items = list(observations.values())
        if abs(items[0]["query_time_s"] - items[1]["query_time_s"]) > self.checks["max_query_skew_seconds"]:
            return self.reject("query_skew")

        self.nodes = nodes
        for node, item in observations.items():
            self.last_revision[node] = item["revision"]

        loads = {node: item["load"] for node, item in observations.items()}
        source = max(loads, key=loads.get)
        target = min(loads, key=loads.get)
        eligible = (
            source != target
            and loads[source] >= self.policy["source_load_min"]
            and loads[target] <= self.policy["target_load_max"]
            and (loads[source] - loads[target] >= self.policy["load_difference_min"]
                 or math.isclose(
                     loads[source] - loads[target],
                     self.policy["load_difference_min"],
                     rel_tol=0.0, abs_tol=1e-12))
        )
        if not eligible:
            self.candidate = None
            self.consecutive = 0
            return {"status": "balanced", "control_executed": False}

        pair = (source, target)
        self.consecutive = self.consecutive + 1 if pair == self.candidate else 1
        self.candidate = pair
        result = {
            "status": "pending", "source": source, "target": target,
            "source_load": loads[source], "target_load": loads[target],
            "independent_pairs": self.consecutive,
            "control_executed": False,
            "collection_window_alignment_validated": False,
            "observation_mode": "asynchronous_latest_unused_sources",
        }
        if self.consecutive >= self.policy["consecutive_independent_pairs"]:
            if (self.last_recommendation is not None
                    and time_s - self.last_recommendation
                    < self.policy["cooldown_seconds"]):
                result["status"] = "cooldown"
            else:
                result["status"] = "recommendation"
                result["action"] = "consider_ue_migration"
                self.last_recommendation = time_s
        return result
