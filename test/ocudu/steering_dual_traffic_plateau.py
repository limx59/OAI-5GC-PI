"""Bounded dual-UE downlink load measurement; no steering control."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import time

PHASES = (
    ("low-before", 200000, 200000),
    ("node-420-3M", 3000000, 200000),
    ("low-middle", 200000, 200000),
    ("node-421-3M", 200000, 3000000),
    ("low-after", 200000, 200000),
)

def measure(command, containers, addresses, dest):
    def traffic(service, port, offered):
        started = datetime.now(timezone.utc)
        raw = command([
            "exec", containers[service],
            "timeout", "--kill-after=5s", "35s",
            "iperf3", "-c", "172.22.0.151", "-p", str(port),
            "-B", addresses[service], "--bind-dev", "oaitun_ue1",
            "-u", "-b", str(offered), "-l", "1200",
            "-t", "20", "-R", "-J", "--get-server-output",
        ], timeout=45)
        finished = datetime.now(timezone.utc)
        data = json.loads(raw)
        if "error" in data:
            raise RuntimeError("iperf reported an error")
        receiver = data["end"]["sum_received"]
        rate = float(receiver["bits_per_second"])
        loss = float(receiver["lost_percent"])
        if not (receiver["bytes"] > 0 and math.isfinite(rate)
                and rate > 0 and math.isfinite(loss) and 0 <= loss <= 100):
            raise RuntimeError("Invalid traffic receiver statistics")
        return raw, {
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "offered_bit_s": offered,
            "receiver": receiver,
            "traffic_quality_passed": (
                0.8 * offered <= rate <= 1.2 * offered and loss <= 5
            ),
        }

    phases = {}
    for name, first, second in PHASES:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = {
                "420": pool.submit(traffic, "nrue", 5201, first),
                "421": pool.submit(traffic, "nrue-2", 5202, second),
            }
            records = {}
            errors = []
            for node, future in jobs.items():
                try:
                    raw, record = future.result()
                    with (dest / f"iperf-{name}-{node}.json").open("x") as stream:
                        stream.write(raw)
                    records[node] = record
                except Exception as error:
                    errors.append(node + ": " + str(error))
        phases[name] = {
            "direction": "downlink",
            "nodes": records,
            "errors": errors,
        }
        # Preserve measurements even if a later phase fails.
        (dest / "traffic-phases.json").write_text(
            json.dumps(phases, indent=2) + "\n"
        )
        if errors:
            raise RuntimeError("Traffic phase failed: " + "; ".join(errors))
        print("MEASURED:", name, flush=True)
        time.sleep(3)
    return phases
