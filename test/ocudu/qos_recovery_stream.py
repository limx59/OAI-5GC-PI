"""Keep QoS state alive across independently managed SDK sessions."""

import csv
from datetime import datetime, timezone
import io
import time

from qos_monitor_state import MonitorState


class RecoveryStream:
    """One serialized supervisor; each SDK session writes a separate CSV."""

    def __init__(self, metrics, clock=time.monotonic):
        self.metrics = tuple(metrics)
        self.monitor = MonitorState(clock=clock)
        self.path = None
        self.used_paths = set()
        self.processed = 0
        self.expected = set()
        self.events = []
        self.observations = []

    def emit(self, events, row=None):
        recorded = []
        for event in events:
            item = {
                **event,
                "received_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            if row is not None:
                item["report_sequence"] = int(row["report_sequence"])
                item["source_received_at_utc"] = row["received_at_utc"]
            self.events.append(item)
            recorded.append(item)
        return recorded

    def begin(self, path):
        path = path.resolve()
        if path in self.used_paths:
            raise ValueError("Each SDK session requires a distinct CSV path")
        self.used_paths.add(path)
        self.path = path
        self.processed = 0
        event = self.monitor.reconnect()
        for node, ue, metric in self.expected:
            self.monitor.register(node, ue, (metric,))
        return self.emit([event])

    def consume(self, row, generation):
        # Reject old-session input before registering keys or changing state.
        if generation != self.monitor.generation:
            return []
        metric = row["measurement"]
        if metric not in self.metrics:
            return []
        node = int(row["node_id"])
        ue = int(row["gnb_cu_ue_f1ap"])
        if node != 420 or int(row["cu_du_id"]) != 0:
            raise ValueError("Expected DU node 420 with DU identifier 0")
        if row["incomplete"] not in ("0", "1"):
            raise ValueError("Invalid incomplete flag")
        if row["value_type"] not in ("integer", "real", "no_value"):
            raise ValueError("Unsupported measurement value type")

        key = (node, ue, metric)
        self.expected.add(key)
        self.monitor.register(node, ue, (metric,))
        sequence = int(row["report_sequence"])
        state = self.monitor.states[key]
        if sequence <= state["sequence"]:
            return []
        value = (
            None if row["value_type"] == "no_value"
            else float(row["value"])
        )
        events = self.monitor.observe(
            generation, node, ue, metric, sequence,
            value=value, incomplete=row["incomplete"] == "1",
        )
        self.observations.append({
            "generation": generation,
            "node": node,
            "ue": ue,
            "metric": metric,
            "report_sequence": sequence,
            "source_received_at_utc": row["received_at_utc"],
            "value": value,
            "incomplete": row["incomplete"],
            "state_after": dict(self.monitor.states[key]),
        })
        return self.emit(events, row)

    def poll(self):
        events = self.emit(self.monitor.expire())
        if self.path is None or not self.path.is_file():
            return events
        text = self.path.read_text()
        # A concurrently appended final line may not yet be complete.
        complete = text[:text.rfind("\n") + 1]
        rows = list(csv.DictReader(io.StringIO(complete)))
        if len(rows) < self.processed:
            raise ValueError("Session CSV was truncated")
        generation = self.monitor.generation
        for row in rows[self.processed:]:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed complete CSV row")
            events.extend(self.consume(row, generation))
            self.processed += 1
        return events
