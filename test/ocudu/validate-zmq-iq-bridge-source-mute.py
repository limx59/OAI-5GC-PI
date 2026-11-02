#!/usr/bin/env python3
"""Synthetic loopback IQ transport check; no laboratory network."""
import json
import signal
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import zmq
from zmq_iq_bridge_core import DTYPE

BLOCK = 11520


def samples(start, count, scale):
    index = np.arange(start, start + count, dtype=np.int64)
    return (scale * ((index % 97) / 128.0
                     + 1j * (index % 89) / 128.0)).astype(DTYPE)


def main():
    context = zmq.Context()
    sockets = []
    process = None

    def socket(kind):
        item = context.socket(kind)
        item.setsockopt(zmq.LINGER, 0)
        sockets.append(item)
        return item

    def bind(item):
        port = item.bind_to_random_port("tcp://127.0.0.1")
        return f"tcp://127.0.0.1:{port}"

    try:
        producers = [socket(zmq.REP) for _ in range(3)]
        inputs = [bind(item) for item in producers]
        consumers = [socket(zmq.REQ) for _ in range(3)]
        # Reserve destination addresses before starting the bridge.
        reservations = [socket(zmq.REP) for _ in range(3)]
        outputs = [bind(item) for item in reservations]
        for item in reservations:
            item.close(linger=0)
        command = [
            sys.executable, "-B", str(Path(__file__).with_name("zmq_iq_bridge_source_mute.py")),
            "--cell-dl", *inputs[:2],
            "--ue-ul", inputs[2],
            "--ue-dl", outputs[0],
            "--cell-ul", *outputs[1:],
            "--dl-gains", "0.55", "0.45",
            "--seconds", "3", "--stall-seconds", "2",
        ]
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        poller = zmq.Poller()
        for item in producers:
            poller.register(item, zmq.POLLIN)
        for item, endpoint in zip(consumers, outputs):
            item.connect(endpoint)
            item.send(b"\x00")
            poller.register(item, zmq.POLLIN)

        mute_signals = 0
        dl_blocks = []
        sent = [0, 0, 0]
        received = [0, 0, 0]
        messages = [0, 0, 0]
        sizes = ((4096, 17001, 8192), (12001, 3000, 16384),
                 (7777, 23111, 1024))
        scales = (0.25, 0.5, 0.75)
        deadline = time.monotonic() + 8
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise TimeoutError("Synthetic bridge test exceeded bound")
            events = dict(poller.poll(10))
            for index, item in enumerate(producers):
                if events.get(item, 0) & zmq.POLLIN:
                    request = item.recv()
                    if request != b"\x00":
                        raise RuntimeError("Invalid bridge sample request")
                    count = sizes[index][messages[index] % 3]
                    item.send(samples(sent[index], count, scales[index]).tobytes())
                    sent[index] += count
                    messages[index] += 1
            for index, item in enumerate(consumers):
                if events.get(item, 0) & zmq.POLLIN:
                    actual = np.frombuffer(item.recv(), DTYPE)
                    start = received[index]
                    if index == 0:
                        a = samples(start, BLOCK, scales[0]).astype(np.complex128)
                        b = samples(start, BLOCK, scales[1]).astype(np.complex128)
                        mixed = (a * 0.55 + b * 0.45).astype(DTYPE)
                        muted = (a * 0.0 + b * 0.45).astype(DTYPE)
                        is_mixed = np.array_equal(actual, mixed)
                        is_muted = np.array_equal(actual, muted)
                        if is_mixed == is_muted:
                            raise RuntimeError("Invalid or ambiguous DL block")
                        dl_blocks.append((start, is_muted))
                        expected = muted if is_muted else mixed
                    else:
                        expected = samples(start, BLOCK, scales[2])
                    if not np.array_equal(actual, expected):
                        raise RuntimeError(f"IQ mismatch on output {index}")
                    received[index] += len(actual)
                    if index == 0:
                        threshold = BLOCK * (20 if mute_signals == 0 else 80)
                        if mute_signals < 2 and received[0] >= threshold:
                            process.send_signal(signal.SIGUSR1)
                            mute_signals += 1
                    item.send(b"\x00")

        stdout, stderr = process.communicate(timeout=2)
        print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        if process.returncode != 0:
            raise RuntimeError("Bridge process failed")
        event_line, report_text = stdout.strip().split("\n", 1)
        event = json.loads(event_line)
        report = json.loads(report_text)
        if event.get("event") != "LAB_SOURCE_MUTED":
            raise RuntimeError("Missing source mute event")
        if mute_signals != 2:
            raise RuntimeError("Repeated mute signal not exercised")
        boundary = report.get("source_mute_dl_sample")
        if not isinstance(boundary, int) or boundary % BLOCK:
            raise RuntimeError("Invalid mute sample boundary")
        if event.get("dl_sample") != boundary:
            raise RuntimeError("Mute event/report mismatch")
        if event.get("gains") != [0.0, 0.45]:
            raise RuntimeError("Unexpected mute gains")
        if report.get("source_mute_gains") != [0.0, 0.45]:
            raise RuntimeError("Unexpected final mute gains")
        if not any(start < boundary for start, _ in dl_blocks):
            raise RuntimeError("No validated samples before mute")
        if not any(start >= boundary for start, _ in dl_blocks):
            raise RuntimeError("No validated samples after mute")
        for start, is_muted in dl_blocks:
            if is_muted != (start >= boundary):
                raise RuntimeError("DL data disagrees with mute boundary")
        print("PASS: exact DL values before and after mute boundary.")
        print("PASS: repeated signal preserves target gain and sample order.")
        if report.get("passed") is not True or min(received) < BLOCK * 10:
            raise RuntimeError("Insufficient validated transport samples")
        print("Validated samples per output:", received)
        print("PASS: unequal input blocks and continuous uplink copies.")
        print("Radio-frame synchronization and live handover remain pending.")
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=3)
        for item in sockets:
            if not item.closed:
                item.close(linger=0)
        context.term()


if __name__ == "__main__":
    main()
