#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$HERE/../.." && pwd)"
RIC_BIN=/usr/local/bin/flexric/ric/nearRT-RIC
AGENT_BIN=/usr/local/bin/flexric/e2agent/emu_agent_gnb
CONTROL_BIN="$PROJECT_ROOT/flexric/build-local/oai-pi-xapp/xapp_handover_control"
RIC_PID=""
AGENT_PID=""

for tool in python3 timeout stdbuf pgrep grep mktemp; do
    command -v "$tool" >/dev/null || {
        echo "Missing command: $tool" >&2
        exit 1
    }
done
for binary in "$RIC_BIN" "$AGENT_BIN" "$CONTROL_BIN"; do
    [[ -x "$binary" ]] || {
        echo "Executable not found: $binary" >&2
        exit 1
    }
done
for config in /usr/local/etc/flexric/{ric,e2agent}.conf "$HERE/xapp.conf"; do
    [[ -r "$config" ]] || {
        echo "Configuration not found: $config" >&2
        exit 1
    }
done

if pgrep -f '^/usr/local/bin/flexric/(ric/nearRT-RIC|e2agent/emu_agent_gnb)( |$)' >/dev/null; then
    echo "An existing lab RIC or emulator is running. Stop it before testing." >&2
    exit 1
fi

LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/oai-pi-xapp-tests.XXXXXXXX")"
echo "Test logs: $LOG_DIR"

stop_child() {
    local pid="$1"
    [[ -n "$pid" ]] || return 0
    kill -INT "$pid" 2>/dev/null || true
    for ((attempt=0; attempt<30; attempt++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null || true
            return 0
        fi
        sleep 0.1
    done
    echo "Child $pid did not stop promptly; sending TERM." >&2
    kill -TERM "$pid" 2>/dev/null || true
    for ((attempt=0; attempt<20; attempt++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null || true
            return 0
        fi
        sleep 0.1
    done
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
}

cleanup() {
    local status=$?
    trap - EXIT
    stop_child "$AGENT_PID"
    stop_child "$RIC_PID"
    echo "Logs retained: $LOG_DIR"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# This runner is restricted to the local lab configuration.
for config in /usr/local/etc/flexric/{ric,e2agent}.conf "$HERE/xapp.conf"; do
    grep -Eq '^[[:space:]]*NearRT_RIC_IP[[:space:]]*=[[:space:]]*"127\.0\.0\.1"' "$config" || {
        echo "Expected loopback RIC address in $config" >&2
        exit 1
    }
done

wait_for_log() {
    local pid="$1" pattern="$2" logfile="$3"
    for ((attempt=0; attempt<100; attempt++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "Process exited during startup: $logfile" >&2
            tail -n 40 "$logfile" >&2
            return 1
        fi
        if grep -Fq "$pattern" "$logfile"; then
            return 0
        fi
        sleep 0.2
    done
    echo "Startup deadline exceeded: $logfile" >&2
    tail -n 40 "$logfile" >&2
    return 1
}

start_pair() {
    local name="$1"
    stdbuf -oL -eL "$RIC_BIN" -c /usr/local/etc/flexric/ric.conf \
        > "$LOG_DIR/$name-ric.log" 2>&1 &
    RIC_PID=$!
    wait_for_log "$RIC_PID" "Initializing Task Manager" "$LOG_DIR/$name-ric.log"
    stdbuf -oL -eL "$AGENT_BIN" -c /usr/local/etc/flexric/e2agent.conf \
        > "$LOG_DIR/$name-agent.log" 2>&1 &
    AGENT_PID=$!
    wait_for_log "$AGENT_PID" "E2 SETUP RESPONSE rx" "$LOG_DIR/$name-agent.log"
}

stop_pair() {
    stop_child "$AGENT_PID"
    AGENT_PID=""
    stop_child "$RIC_PID"
    RIC_PID=""
}

run_case() {
    local name="$1" expected="$2" agent_expected="$3"
    shift 3
    echo "Running: $name"
    start_pair "$name"
    if timeout --kill-after=5s 35s "$@" > "$LOG_DIR/$name-xapp.log" 2>&1; then
        :
    else
        local status=$?
        echo "FAIL: $name, exit status $status" >&2
        tail -n 40 "$LOG_DIR/$name-xapp.log" >&2
        return 1
    fi
    if ! kill -0 "$RIC_PID" 2>/dev/null ||
       ! kill -0 "$AGENT_PID" 2>/dev/null; then
        echo "FAIL: RIC or agent exited during $name" >&2
        return 1
    fi
    grep -Fq "$expected" "$LOG_DIR/$name-xapp.log" || {
        echo "FAIL: expected xApp output missing for $name" >&2
        return 1
    }
    if [[ -n "$agent_expected" ]]; then
        grep -Fq "$agent_expected" "$LOG_DIR/$name-agent.log" || {
            echo "FAIL: expected agent output missing for $name" >&2
            return 1
        }
    fi
    stop_pair
    echo "PASS: $name"
}

run_case nodes "Connected E2 nodes: 1" "" \
    python3 "$HERE/xapp_nodes.py" -c "$HERE/xapp.conf"

run_case kpm "DRB.UEThpDl =" "" \
    python3 "$HERE/xapp_kpm.py" -c "$HERE/xapp.conf"
grep -Fq "DRB.UEThpUl =" "$LOG_DIR/kpm-xapp.log"

run_case radio "MAC node=1" "" \
    python3 "$HERE/xapp_radio_stats.py" -c "$HERE/xapp.conf"
grep -Fq "RLC node=1" "$LOG_DIR/radio-xapp.log"
grep -Fq "PDCP node=1" "$LOG_DIR/radio-xapp.log"

run_case recorder "Recorded " "" \
    env XAPP_OUTPUT="$LOG_DIR/kpm.csv" \
    python3 "$HERE/xapp_kpm_recorder.py" -c "$HERE/xapp.conf"

python3 - "$LOG_DIR/kpm.csv" <<'CSV_CHECK'
import csv
import math
import sys

with open(sys.argv[1], newline="", encoding="utf-8") as stream:
    rows = list(csv.DictReader(stream))
assert rows, "No CSV measurements"
assert all(None not in row and None not in row.values() for row in rows)
assert {row["measurement"] for row in rows} == {"DRB.UEThpDl", "DRB.UEThpUl"}
for row in rows:
    assert row["node_id"] == "1"
    assert row["value_type"] in ("integer", "real")
    assert math.isfinite(float(row["value"]))
print(f"PASS: CSV validation ({len(rows)} measurements)")
CSV_CHECK

run_case qos "ALERT: node=1 metric=DRB.UEThpDl" "" \
    env XAPP_QOS_THRESHOLD=1000000000 XAPP_QOS_LOW_REPORTS=2 \
    python3 "$HERE/xapp_qos_watch.py" -c "$HERE/xapp.conf"
grep -Fq "ALERT: node=1 metric=DRB.UEThpUl" "$LOG_DIR/qos-xapp.log"

run_case slice "Successfully received CONTROL-ACK" "SLICE CONTROL ADD rx" \
    env XAPP_SLICE_INPUT="$HERE/slice_samples.json" \
    python3 "$HERE/xapp_slice_control.py" -c "$HERE/xapp.conf"

run_case steering "Control process completed." \
    "handover ran_ue_id 1 to target cell NR_CGI 512" \
    python3 "$HERE/xapp_steering_control.py" --send-emulator \
    "$HERE/traffic_samples.json" --mapping "$HERE/steering_lab.json" \
    --config "$HERE/xapp.conf" --binary "$CONTROL_BIN"


python3 - "$LOG_DIR" <<'LOG_CHECK'
import sys
from pathlib import Path

root = Path(sys.argv[1])
for name in ("nodes", "kpm", "radio", "recorder", "qos", "slice", "steering"):
    text = (root / f"{name}-xapp.log").read_text()
    assert "callback error" not in text.lower(), f"{name}: callback failed"

for name, expected in (("kpm", 1), ("radio", 3), ("recorder", 1), ("qos", 1)):
    text = (root / f"{name}-xapp.log").read_text()
    count = text.count("SUBSCRIPTION DELETE RESPONSE rx")
    assert count == expected, f"{name}: expected {expected} delete responses, got {count}"

for name, marker in (
    ("slice", "SLICE CONTROL ADD rx"),
    ("steering", "Recv control message for handover"),
):
    agent = (root / f"{name}-agent.log").read_text()
    assert agent.count(marker) == 1, f"{name}: expected one control request"
    assert agent.count("CONTROL ACKNOWLEDGE tx") == 1, f"{name}: missing agent ACK"
    xapp = (root / f"{name}-xapp.log").read_text()
    assert "Successfully received CONTROL-ACK" in xapp, f"{name}: missing xApp ACK"

print("PASS: callbacks, subscription cleanup, and single-request control checks")
LOG_CHECK

echo "PASS: all seven emulator cases and final checks"
