"""Bounded IQ buffering for laboratory same-rate ZMQ streams."""
from collections import deque
import numpy as np

DTYPE = np.dtype("<c8")


class SampleFIFO:
    """Preserve sample order across arbitrary transport message boundaries."""

    def __init__(self, limit_samples):
        if not isinstance(limit_samples, int) or limit_samples <= 0:
            raise ValueError("Invalid sample limit")
        self.limit = limit_samples
        self.blocks = deque()
        self.offset = 0
        self.available = 0
        self.received = 0
        self.consumed = 0

    def push(self, payload):
        if not payload or len(payload) % DTYPE.itemsize:
            raise ValueError("Invalid complex-float payload length")
        count = len(payload) // DTYPE.itemsize
        if self.available + count > self.limit:
            raise BufferError("IQ sample buffer limit exceeded")
        block = np.frombuffer(payload, dtype=DTYPE).copy()
        if not np.isfinite(block).all():
            raise ValueError("Non-finite IQ samples")
        self.blocks.append(block)
        self.available += count
        self.received += count

    def pop(self, count):
        if not isinstance(count, int) or count <= 0:
            raise ValueError("Invalid sample count")
        if count > self.available:
            raise BufferError("Insufficient IQ samples")
        result = np.empty(count, dtype=DTYPE)
        written = 0
        while written < count:
            block = self.blocks[0]
            take = min(count - written, len(block) - self.offset)
            result[written:written + take] = block[self.offset:self.offset + take]
            written += take
            self.offset += take
            if self.offset == len(block):
                self.blocks.popleft()
                self.offset = 0
        self.available -= count
        self.consumed += count
        return result


def mix_downlink(first, second, count, gains=(0.5, 0.5)):
    """Combine equal-rate streams at the same relative sample position.

    The caller must establish a shared sample origin before using this.
    Equal counters alone do not establish radio-frame synchronization.
    """
    if first is second:
        raise ValueError("Two independent streams required")
    if first.consumed != second.consumed:
        raise ValueError("Stream sample positions differ")
    if not isinstance(count, int) or count <= 0:
        raise ValueError("Invalid sample count")
    weights = np.asarray(gains, dtype=np.float64)
    if weights.shape != (2,) or not np.isfinite(weights).all():
        raise ValueError("Invalid gains")
    if np.any(weights < 0) or weights.sum() > 1.0:
        raise ValueError("Gains must be nonnegative with sum at most one")
    if min(first.available, second.available) < count:
        raise BufferError("Both streams must contain the requested samples")
    a = first.pop(count)
    b = second.pop(count)
    with np.errstate(over="raise", invalid="raise"):
        mixed = a.astype(np.complex128) * weights[0]
        mixed += b.astype(np.complex128) * weights[1]
        result = mixed.astype(DTYPE)
    if not np.isfinite(result).all():
        raise ValueError("Non-finite mixed IQ samples")
    return result.tobytes()
