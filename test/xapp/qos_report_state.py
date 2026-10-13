"""Track report silence independently for each node and metric."""

import math
import time


class ReportState:
    def __init__(self, timeout, clock=time.monotonic):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Report timeout must be finite and positive.")
        self.timeout = timeout
        self.clock = clock
        self.last_seen = {}
        self.stale = set()

    def register(self, keys):
        """Start monitoring subscribed metrics, including first-report silence."""
        now = self.clock()
        for key in keys:
            self.last_seen.setdefault(key, now)

    def observe(self, keys):
        """Return stale keys whose valid measurements have resumed."""
        now = self.clock()
        recovered = []
        for key in keys:
            self.last_seen[key] = now
            if key in self.stale:
                self.stale.remove(key)
                recovered.append(key)
        return recovered

    def expire(self):
        """Return newly stale keys once per silence episode."""
        now = self.clock()
        expired = []
        for key, last in self.last_seen.items():
            if now - last >= self.timeout and key not in self.stale:
                self.stale.add(key)
                expired.append(key)
        return expired
