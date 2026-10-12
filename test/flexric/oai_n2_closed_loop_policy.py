"""Experimental actual-MAC-rate policy; not a capacity or utilization model."""
from dataclasses import dataclass

CELLS = {3584: 12345678, 2816: 720898}

@dataclass
class Policy:
    high_bytes_per_second: float = 100000
    low_bytes_per_second: float = 25000
    cooldown_seconds: float = 30
    max_actions: int = 2
    actions: int = 0
    last_action: float = float("-inf")
    armed: bool = True
    pending: bool = False

    def rates(self, reports, node, now):
        items = sorted(
            (r for r in reports if r["node"] == node
             and now - 4.5 <= r["report_us"] / 1e6 <= now),
            key=lambda r: r["report_us"])
        if len(items) < 2:
            return None, "missing_mac"
        latest = items[-1]["report_us"] / 1e6
        if now - latest > 2:
            return None, "stale_mac"
        for r in items:
            if r["ues"] != 1 or len(r["stats"]) != 1:
                return None, "unexpected_ue_count"
            if abs(r["received_us"] - r["report_us"]) > 2000000:
                return None, "delayed_mac"
        rnti = items[-1]["stats"][0]["rnti"]
        if any(r["stats"][0]["rnti"] != rnti for r in items):
            return None, "rnti_changed"
        for a, b in zip(items, items[1:]):
            dt = (b["report_us"] - a["report_us"]) / 1e6
            if dt <= 0 or dt > 0.5:
                return None, "report_gap"
            for key in ("ul_bytes", "dl_bytes", "ul_prb", "dl_prb"):
                if b["stats"][0][key] < a["stats"][0][key]:
                    return None, "counter_reset"
        windows = []
        for offset in (3, 2, 1):
            low, high = latest - offset, latest - offset + 1
            window = [r for r in items if low <= r["report_us"] / 1e6 <= high]
            if len(window) < 2:
                return None, "short_window"
            a, b = window[0], window[-1]
            dt = (b["report_us"] - a["report_us"]) / 1e6
            if dt < 0.8:
                return None, "short_window"
            windows.append(
                (b["stats"][0]["ul_bytes"] - a["stats"][0]["ul_bytes"]) / dt)
        return windows, "valid"

    def evaluate(self, reports, source, inventory, now):
        target = 2816 if source == 3584 else 3584
        result = {"action": False, "source": source, "target": target}
        if source not in CELLS:
            return dict(result, reason="unknown_source")
        if self.pending:
            return dict(result, reason="awaiting_feedback")
        rates, reason = self.rates(reports, source, now)
        if rates is None:
            return dict(result, reason=reason)
        result["ul_bytes_per_second"] = rates
        if all(rate <= self.low_bytes_per_second for rate in rates):
            self.armed = True
        if self.actions >= self.max_actions:
            return dict(result, reason="action_limit")
        if now - self.last_action < self.cooldown_seconds:
            return dict(result, reason="cooldown")
        if not self.armed:
            return dict(result, reason="requires_low_rate_rearm")
        if not all(rate >= self.high_bytes_per_second for rate in rates):
            return dict(result, reason="below_threshold")
        state = inventory.get(target)
        if not state or state.get("valid") is not True:
            return dict(result, reason="missing_target_inventory")
        age = now - state["received_us"] / 1e6
        if not 0 <= age <= 15:
            return dict(result, reason="stale_target_inventory")
        if state["node"] != target or state["cell"] != CELLS[target]:
            return dict(result, reason="target_identity_mismatch")
        if state["ues"] != 0:
            return dict(result, reason="target_occupied")
        return dict(result, action=True, reason="confirmed_actual_mac_rate")

    def submitted(self, now):
        if self.pending:
            raise RuntimeError("A control request is already pending")
        self.pending = True
        self.armed = False
        self.actions += 1
        self.last_action = now

    def feedback(self, source, target, inventory):
        if not self.pending:
            raise RuntimeError("No pending request")
        for node, count in ((source, 0), (target, 1)):
            state = inventory[node]
            if (state.get("valid") is not True or state["node"] != node
                    or state["cell"] != CELLS[node] or state["ues"] != count
                    or state["received_us"] / 1e6 < self.last_action):
                raise RuntimeError("Fresh post-control cell feedback not confirmed")
        self.pending = False
