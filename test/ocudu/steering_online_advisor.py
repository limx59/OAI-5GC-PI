"""Online laboratory advisory adapter; no control API."""
from collections import Counter
import copy
import json
import math
import time

from steering_embedded_policy_async import EmbeddedSteeringPolicy

class OnlineAdvisor:
    def __init__(self, config, output):
        self.policy = EmbeddedSteeringPolicy(copy.deepcopy(config))
        self.output = output
        self.latest = {}
        self.seen = {}
        self.counts = Counter()
        self.recommendations = []
        with output.open("x") as stream:
            pass

    def reject(self, reason):
        self.policy.reject(reason)
        self.counts["rejected:" + reason] += 1

    def observe(self, node, values):
        if node not in ("420", "421"):
            raise ValueError("Unexpected advisory node")

        def integer(name, maximum):
            value = values[name]
            if (isinstance(value, bool) or not isinstance(value, int)
                    or not 0 <= value <= maximum):
                raise ValueError("Invalid metadata: " + name)
            return value

        revision = integer("OAI.PI.PrbSourceRevision", 2147483647)
        if revision == 0:
            raise ValueError("Source revision is zero")
        stamps = []
        for stem in ("OAI.PI.PrbReceiptMono", "OAI.PI.PrbQueryMono"):
            seconds = integer(stem + "Sec", 2147483647)
            micros = integer(stem + "Usec", 999999)
            stamps.append(seconds * 1000000 + micros)
        receipt_us, query_us = stamps
        load = values["RRU.PrbTotDl"]
        if (isinstance(load, bool) or not isinstance(load, (int, float))
                or not math.isfinite(load) or not 0 <= load <= 100):
            raise ValueError("Invalid PRB load")

        now = time.monotonic()
        now_us = int(now * 1000000)
        if not 0 < receipt_us <= query_us <= now_us:
            self.reject("clock_order_or_domain")
            return
        if now - query_us / 1e6 > self.policy.checks["max_receipt_age_seconds"]:
            self.reject("query_delivery_too_old")
            return

        previous = self.seen.get(node)
        if previous is not None:
            old_revision, old_receipt, old_load, old_query = previous
            if revision < old_revision or query_us < old_query:
                raise ValueError("Source restart or out-of-order report")
            if revision == old_revision and (receipt_us, load) != (
                    old_receipt, old_load):
                raise ValueError("Same source revision changed metadata or load")
        self.seen[node] = (revision, receipt_us, load, query_us)
        self.latest[node] = {
            "revision": revision,
            "load": load / 100,
            "query_time_s": query_us / 1e6,
            "receipt_time_s": receipt_us / 1e6,
        }
        self.counts["observations"] += 1
        if len(self.latest) != 2:
            return
        if any(item["revision"] <= self.policy.last_revision.get(n, 0)
               for n, item in self.latest.items()):
            self.counts["waiting_for_two_unused_sources"] += 1
            return

        result = self.policy.evaluate(now, self.latest)
        self.counts[result["status"]] += 1
        if result["status"] == "input_rejected":
            self.counts["rejected:" + result["reason"]] += 1
        entry = {
            "decision_monotonic_seconds": now,
            "revisions": {n: item["revision"]
                          for n, item in self.latest.items()},
            "observations": copy.deepcopy(self.latest),
            "result": result,
        }
        with self.output.open("a") as stream:
            stream.write(json.dumps(entry, sort_keys=True) + "\n")
        if result["status"] == "recommendation":
            self.recommendations.append(entry)
            print("ONLINE_ADVISORY " + json.dumps(entry, sort_keys=True),
                  flush=True)

    def summary(self):
        return {
            "scope": "Same-host asynchronous laboratory online advisory",
            "counts": dict(self.counts),
            "recommendations": self.recommendations,
            "control_executed": False,
            "collection_window_alignment_validated": False,
        }
