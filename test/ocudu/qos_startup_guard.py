"""Bounded host I/O readiness check before starting a QoS test."""

from datetime import datetime, timezone
import json
from pathlib import Path
import time


def snapshot():
    lines = Path("/proc/stat").read_text().splitlines()
    cpu = next(line for line in lines if line.startswith("cpu "))
    values = list(map(int, cpu.split()[1:]))
    # Guest times are already included in user/nice; exclude them here.
    total = sum(values[:8])
    iowait = values[4]
    blocked = int(next(
        line.split()[1] for line in lines
        if line.startswith("procs_blocked ")
    ))
    return total, iowait, blocked


def wait_host_ready(output, stable_samples=3, max_seconds=30):
    """Require consecutive samples below experimental I/O guard limits."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    if stable_samples < 1 or max_seconds < stable_samples + 1:
        raise ValueError("Invalid readiness sampling bounds")

    result = {
        "passed": False,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "basis": "host readiness only; not an AUSF or SBI health check",
        "thresholds": {
            "iowait_percent_below": 50,
            "blocked_tasks_below": 16,
            "consecutive_samples": stable_samples,
            "max_seconds": max_seconds,
        },
        "samples": [],
    }
    streak = 0
    previous = snapshot()
    deadline = time.monotonic() + max_seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(1)
            current = snapshot()
            total = current[0] - previous[0]
            waiting = current[1] - previous[1]
            previous = current
            if total <= 0 or waiting < 0:
                streak = 0
                continue
            percent = 100.0 * waiting / total
            ready = percent < 50 and current[2] < 16
            streak = streak + 1 if ready else 0
            result["samples"].append({
                "utc": datetime.now(timezone.utc).isoformat(),
                "iowait_percent": round(percent, 2),
                "blocked_tasks": current[2],
                "ready_streak": streak,
            })
            if streak >= stable_samples:
                result["passed"] = True
                return result
        raise RuntimeError(
            "Host I/O readiness timeout; no test should be started"
        )
    finally:
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        with output.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
