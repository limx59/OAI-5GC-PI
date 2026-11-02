#!/usr/bin/env python3
"""Bounded laboratory two-cell IQ bridge; no control requests."""
import argparse
import json
import signal
import time
import zmq
from zmq_iq_bridge_core import SampleFIFO, mix_downlink

MAX_MESSAGE_SAMPLES = 300000
BUFFER_SAMPLES = 600000
BLOCK_SAMPLES = 11520


def run(args):
    endpoints = args.cell_dl + args.cell_ul + [args.ue_dl, args.ue_ul]
    if len(set(endpoints)) != 6:
        raise ValueError("Six distinct endpoints required")
    if not all(value.startswith("tcp://") for value in endpoints):
        raise ValueError("TCP endpoints required")
    if not (0 < args.seconds <= 300 and 0 < args.stall_seconds <= 30):
        raise ValueError("Invalid runtime bounds")

    context = zmq.Context()
    sockets = []
    poller = zmq.Poller()
    stopping = False
    mute_requested = False
    source_muted = False
    stats = {"passed": False, "dl_samples": 0, "ul_samples": [0, 0],
             "scope": "IQ transport only; radio synchronization unvalidated"}

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    old_handlers = {sig: signal.signal(sig, stop)
                    for sig in (signal.SIGINT, signal.SIGTERM)}

    def request_source_mute(signum, frame):
        nonlocal mute_requested
        mute_requested = True

    old_handlers[signal.SIGUSR1] = signal.signal(
        signal.SIGUSR1, request_source_mute
    )

    def socket(kind, address, bind):
        item = context.socket(kind)
        sockets.append(item)
        item.setsockopt(zmq.LINGER, 0)
        item.setsockopt(zmq.SNDHWM, 2)
        item.setsockopt(zmq.RCVHWM, 2)
        item.setsockopt(zmq.MAXMSGSIZE, MAX_MESSAGE_SAMPLES * 8)
        (item.bind if bind else item.connect)(address)
        poller.register(item, zmq.POLLIN)
        return item

    try:
        dl = [socket(zmq.REQ, value, False) for value in args.cell_dl]
        ul = socket(zmq.REQ, args.ue_ul, False)
        out = [socket(zmq.REP, args.ue_dl, True)]
        out += [socket(zmq.REP, value, True) for value in args.cell_ul]
        sources = dl + [ul]
        outstanding = {item: False for item in sources}
        waiting = {item: False for item in out}
        down = [SampleFIFO(BUFFER_SAMPLES) for _ in range(2)]
        up = [SampleFIFO(BUFFER_SAMPLES) for _ in range(2)]
        started = progress = time.monotonic()

        while not stopping:
            now = time.monotonic()
            if now - started >= args.seconds:
                stats["completed_bound"] = True
                break
            if now - progress > args.stall_seconds:
                raise TimeoutError("IQ bridge made no sample progress")

            for index, item in enumerate(sources):
                buffers = [down[index]] if index < 2 else up
                if (not outstanding[item]
                        and all(f.available <= BUFFER_SAMPLES - MAX_MESSAGE_SAMPLES
                                for f in buffers)):
                    try:
                        item.send(b"\x00", zmq.DONTWAIT)
                    except zmq.Again:
                        continue
                    outstanding[item] = True

            events = dict(poller.poll(10))
            for index, item in enumerate(sources):
                if events.get(item, 0) & zmq.POLLIN:
                    if not outstanding[item]:
                        raise RuntimeError("Unexpected sample response")
                    payload = item.recv(zmq.DONTWAIT)
                    if item.getsockopt(zmq.RCVMORE):
                        raise ValueError("Multipart samples unsupported")
                    if len(payload) > MAX_MESSAGE_SAMPLES * 8:
                        raise ValueError("Sample message exceeds bound")
                    targets = [down[index]] if index < 2 else up
                    for fifo in targets:
                        fifo.push(payload)
                    outstanding[item] = False

            for item in out:
                if not waiting[item] and events.get(item, 0) & zmq.POLLIN:
                    request = item.recv(zmq.DONTWAIT)
                    if item.getsockopt(zmq.RCVMORE) or len(request) != 1:
                        raise ValueError("Expected one-byte sample request")
                    waiting[item] = True
                    # A REP socket cannot receive again until it has replied.
                    poller.unregister(item)

            for index, item in enumerate(out):
                if not waiting[item]:
                    continue
                available = (min(f.available for f in down)
                             if index == 0 else up[index - 1].available)
                if available < BLOCK_SAMPLES:
                    continue
                if not item.poll(0, zmq.POLLOUT):
                    continue
                if index == 0 and mute_requested and not source_muted:
                    args.dl_gains = (0.0, args.dl_gains[1])
                    source_muted = True
                    stats["source_mute_dl_sample"] = stats["dl_samples"]
                    stats["source_mute_gains"] = list(args.dl_gains)
                    print(json.dumps({
                        "event": "LAB_SOURCE_MUTED",
                        "dl_sample": stats["dl_samples"],
                        "gains": list(args.dl_gains),
                    }), flush=True)
                payload = (mix_downlink(*down, BLOCK_SAMPLES, args.dl_gains)
                           if index == 0 else up[index - 1].pop(
                               BLOCK_SAMPLES).tobytes())
                item.send(payload, zmq.DONTWAIT)
                waiting[item] = False
                poller.register(item, zmq.POLLIN)
                if index == 0:
                    stats["dl_samples"] += BLOCK_SAMPLES
                else:
                    stats["ul_samples"][index - 1] += BLOCK_SAMPLES
                progress = time.monotonic()

        stats["stopped_by_signal"] = stopping
        stats["passed"] = (not stopping and stats["dl_samples"] > 0
                           and min(stats["ul_samples"]) > 0)
    except Exception as error:
        stats["error"] = str(error)
    finally:
        for item in sockets:
            item.close(linger=0)
        context.term()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        print(json.dumps(stats, indent=2), flush=True)
    return 0 if stats["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell-dl", nargs=2, required=True)
    parser.add_argument("--cell-ul", nargs=2, required=True)
    parser.add_argument("--ue-dl", required=True)
    parser.add_argument("--ue-ul", required=True)
    parser.add_argument("--dl-gains", nargs=2, type=float, default=(0.5, 0.5))
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--stall-seconds", type=float, default=10)
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
