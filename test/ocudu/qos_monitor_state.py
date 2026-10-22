"""Normalize OCUDU DU KPM values and track advisory QoS state."""

import math
import time

# Raw unit, normalized unit, scale, bad direction, alert and clear limits.
RULES = {
    "DRB.UEThpDl": ("kbps", "bit/s", 1000.0, "low", 500000.0, 800000.0),
    "DRB.UEThpUl": ("kbps", "bit/s", 1000.0, "low", 500000.0, 800000.0),
    "DRB.RlcSduDelayDl": ("0.1 ms", "ms", 0.1, "high", 50.0, 40.0),
    "DRB.RlcDelayUl": ("0.1 ms", "ms", 0.1, "high", 50.0, 40.0),
    "DRB.RlcPacketDropRateDl": ("percent", "percent", 1.0, "high", 5.0, 2.0),
}


def normalize(metric, value):
    rule = RULES[metric]
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid value for {metric}: {value!r}")
    if metric == "DRB.RlcPacketDropRateDl" and number > 100:
        raise ValueError("Drop percentage outside 0..100")
    return number * rule[2]


class MonitorState:
    """Per-key state; callers serialize access from SDK and watchdog threads."""

    def __init__(self, consecutive=3, timeout=5.0, clock=time.monotonic):
        if type(consecutive) is not int or consecutive < 1:
            raise ValueError("consecutive must be a positive integer")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.consecutive = consecutive
        self.timeout = timeout
        self.clock = clock
        self.generation = 0
        self.states = {}

    def reconnect(self):
        """Begin a new subscription generation without inheriting old counters."""
        old = self.generation
        self.generation += 1
        self.states.clear()
        return {
            "event": "SESSION_RESET",
            "previous_generation": old,
            "generation": self.generation,
            "mode": "advisory",
        }

    def register(self, node, ue, metrics):
        now = self.clock()
        for metric in metrics:
            if metric not in RULES:
                raise ValueError(f"Unsupported metric: {metric}")
            key = (node, ue, metric)
            self.states.setdefault(key, {
                "status": "UNKNOWN",
                "last_valid": now,
                "sequence": -1,
                "bad_count": 0,
                "clear_count": 0,
            })

    def event(self, label, key, **extra):
        node, ue, metric = key
        return {
            "event": label,
            "generation": self.generation,
            "node": node,
            "ue": ue,
            "metric": metric,
            "mode": "advisory",
            **extra,
        }

    def observe(self, generation, node, ue, metric, sequence,
                value=None, incomplete=False):
        if generation != self.generation:
            return []
        key = (node, ue, metric)
        if key not in self.states:
            raise ValueError("Register the expected metric before observation")
        state = self.states[key]
        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence must be a nonnegative integer")
        if sequence <= state["sequence"]:
            return []
        state["sequence"] = sequence

        number = None
        if value is not None and not incomplete:
            number = normalize(metric, value)
        if number is None:
            state["bad_count"] = state["clear_count"] = 0
            if state["status"] not in ("UNKNOWN", "STALE"):
                state["status"] = "UNKNOWN"
                return [self.event("UNKNOWN", key)]
            return []

        events = []
        previous = state["status"]
        state["last_valid"] = self.clock()
        if previous in ("UNKNOWN", "STALE"):
            state["status"] = "OBSERVING"
            state["bad_count"] = state["clear_count"] = 0
            events.append(self.event("REPORT_RESUMED", key))

        rule = RULES[metric]
        bad = number < rule[4] if rule[3] == "low" else number > rule[4]
        clear = number >= rule[5] if rule[3] == "low" else number <= rule[5]
        if state["status"] == "ALERT":
            state["clear_count"] = state["clear_count"] + 1 if clear else 0
            if state["clear_count"] >= self.consecutive:
                state["status"] = "HEALTHY"
                state["clear_count"] = state["bad_count"] = 0
                events.append(self.event("RECOVERY", key, value=number))
        else:
            state["bad_count"] = state["bad_count"] + 1 if bad else 0
            if state["bad_count"] >= self.consecutive:
                state["status"] = "ALERT"
                state["clear_count"] = 0
                events.append(self.event(
                    "ALERT", key, value=number,
                    consecutive=state["bad_count"],
                ))
            elif clear:
                state["status"] = "HEALTHY"
        return events

    def expire(self):
        now = self.clock()
        events = []
        for key, state in self.states.items():
            if (now - state["last_valid"] >= self.timeout
                    and state["status"] != "STALE"):
                state["status"] = "STALE"
                state["bad_count"] = state["clear_count"] = 0
                events.append(self.event("STALE", key))
        return events
