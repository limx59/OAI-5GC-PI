#!/usr/bin/env python3
"""Offline numerical checks; no RAN, SDK or network connection."""
import numpy as np
from zmq_iq_bridge_core import DTYPE, SampleFIFO, mix_downlink


def require(value, message):
    if not value:
        raise RuntimeError(message)


def rejects(exception, operation):
    try:
        operation()
    except exception:
        return
    raise RuntimeError("Expected rejection: " + exception.__name__)


def state(fifo):
    return fifo.available, fifo.received, fifo.consumed


def main():
    source = np.arange(257, dtype=np.float32).astype(DTYPE)
    source += 1j * source[::-1].copy()
    fifo = SampleFIFO(300)
    for block in np.array_split(source, [1, 17, 18, 200]):
        fifo.push(block.tobytes())
    actual = np.concatenate([fifo.pop(n) for n in (3, 99, 1, 154)])
    require(np.array_equal(actual, source), "Sample order changed")
    require(state(fifo) == (0, 257, 257), "Incorrect FIFO counters")
    print("PASS: sample order across unequal message boundaries")

    first, second = SampleFIFO(300), SampleFIFO(300)
    other = (source * np.complex64(-0.25 + 0.5j)).astype(DTYPE)
    for block in np.array_split(source, [13, 80]):
        first.push(block.tobytes())
    for block in np.array_split(other, [1, 100, 240]):
        second.push(block.tobytes())
    mixed = b"".join(mix_downlink(first, second, n, (0.75, 0.25))
                     for n in (7, 128, 122))
    expected = (source.astype(np.complex128) * 0.75
                + other.astype(np.complex128) * 0.25).astype(DTYPE)
    require(np.array_equal(np.frombuffer(mixed, DTYPE), expected),
            "Incorrect weighted IQ sum")
    require(state(first) == state(second) == (0, 257, 257),
            "Mixed streams lost sample alignment")
    print("PASS: weighted sum independent of transport segmentation")

    fifo = SampleFIFO(2)
    fifo.push(np.array([1 + 2j], dtype=DTYPE).tobytes())
    before = state(fifo)
    rejects(BufferError, lambda: fifo.push(bytes(16)))
    rejects(BufferError, lambda: fifo.pop(2))
    rejects(ValueError, lambda: fifo.push(b"x"))
    rejects(ValueError, lambda: fifo.push(b""))
    rejects(ValueError, lambda: fifo.push(
        np.array([complex(float("nan"), 0)], dtype=DTYPE).tobytes()))
    require(state(fifo) == before, "Rejected input changed FIFO counters")
    require(fifo.pop(1)[0] == 1 + 2j, "Rejected input changed buffered data")
    print("PASS: bounded buffering and invalid payload rejection")

    first, second = SampleFIFO(4), SampleFIFO(4)
    first.push(bytes(24))
    second.push(bytes(8))
    before = state(first), state(second)
    rejects(BufferError, lambda: mix_downlink(first, second, 2))
    rejects(ValueError, lambda: mix_downlink(first, second, 1, (1, 1)))
    require((state(first), state(second)) == before,
            "Rejected mix consumed samples")
    first.pop(1)
    rejects(ValueError, lambda: mix_downlink(first, second, 1))
    print("PASS: insufficient data, invalid gains and position mismatch rejection")
    print("PASS: offline IQ core checks; radio synchronization and live transport remain pending.")


if __name__ == "__main__":
    main()
