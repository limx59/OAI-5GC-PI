#!/usr/bin/env python3
"""Confirm lab queue-based recommendations; never send or commit controls.

Freshness refers to host log queries, not source collection time.
Thresholds classify post-grant bytes, not PRB demand percentages.
"""
from copy import deepcopy
import math


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, float)) and math.isfinite(value))


class QueuePolicy:
    def __init__(self, sources, high_bytes=32768, low_bytes=1024, max_age_s=7):
        require(isinstance(sources, dict) and set(sources) == {"420", "421"}
                and all(isinstance(v, str) and v for v in sources.values()),
                "Expected explicit source instances for both nodes")
        require(type(high_bytes) is int and type(low_bytes) is int
                and 0 <= low_bytes < high_bytes, "Invalid byte thresholds")
        require(finite(max_age_s) and max_age_s > 0, "Invalid age limit")
        self.sources = deepcopy(sources)
        self.high = high_bytes
        self.low = low_bytes
        self.max_age = max_age_s
        self.previous = {}
        self.last_now = None
        self.candidate = None
        self.confirmations = 0

    def evaluate(self, now, reports):
        require(finite(now) and now >= 0
                and (self.last_now is None or now >= self.last_now),
                "Invalid decision time")
        require(isinstance(reports, dict) and set(reports) == set(self.sources),
                "Both node reports required")
        next_previous = {}
        maxima = {}
        for node, report in reports.items():
            require(isinstance(report, dict)
                    and report.get("node_id") == node
                    and report.get("source_instance") == self.sources[node],
                    "Unexpected report source")
            revision = report.get("revision")
            start = report.get("host_query_start_s")
            end = report.get("host_query_end_s")
            require(type(revision) is int and revision > 0,
                    "Invalid revision")
            require(finite(start) and finite(end) and 0 <= start < end <= now
                    and now - end <= self.max_age,
                    "Invalid or stale host query interval")
            if node in self.previous:
                prior_revision, prior_end = self.previous[node]
                require(revision > prior_revision and start >= prior_end,
                        "Duplicate revision or overlapping query")
            require(report.get("queue_unit") == "bytes"
                    and report.get("prb_demand_percent_established") is False,
                    "Unexpected observation semantics")
            samples = report.get("samples")
            require(isinstance(samples, list)
                    and type(report.get("sample_count")) is int
                    and report["sample_count"] == len(samples),
                    "Invalid sample count")
            values = []
            for sample in samples:
                require(isinstance(sample, dict), "Invalid queue sample")
                value = sample.get("pending_dl_bytes_after_grant")
                require(type(value) is int and value >= 0,
                        "Invalid queue bytes")
                values.append(value)
            statistics = ({
                "minimum": min(values), "maximum": max(values),
                "positive_samples": sum(v > 0 for v in values),
            } if values else None)
            require(report.get("queue_statistics") == statistics
                    and report.get("observation_status") ==
                    ("observed" if values else "unknown"),
                    "Inconsistent queue evidence")
            maxima[node] = max(values) if values else None
            next_previous[node] = (revision, end)

        candidate = None
        # Unknown peer evidence blocks a joint recommendation.
        if all(v is not None for v in maxima.values()):
            if max(maxima.values()) >= self.high:
                candidate = "limited"
            elif max(maxima.values()) <= self.low:
                candidate = "normal"

        count = (self.confirmations + 1
                 if candidate is not None and candidate == self.candidate
                 else 1 if candidate is not None else 0)
        self.previous = next_previous
        self.last_now = now
        self.candidate = candidate
        self.confirmations = count
        confirmed = candidate is not None and count >= 2
        return {
            "status": "confirmed" if confirmed else
                      "pending_confirmation" if candidate else "hold",
            "candidate": candidate,
            "confirmations": count,
            "window_maximum_bytes": maxima,
            "recommended_max_ratio": (
                20 if candidate == "limited" else 100
            ) if confirmed else None,
            "control_requests_sent": 0,
            "scheduler_execution_validated": False,
            "source_collection_time_validated": False,
        }
