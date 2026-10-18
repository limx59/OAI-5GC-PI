#!/usr/bin/env python3
"""Experiment: yield the CPU on empty OCUDU ZeroMQ polling paths."""

import argparse
from pathlib import Path


def patch_function(text, signature, old, new):
    if text.count(signature) != 1:
        raise SystemExit(f"STOP: unexpected function anchor: {signature}")
    start = text.index(signature)
    end = text.index("\n}\n", start) + len("\n}\n")
    body = text[start:end]
    if body.count(old) != 1:
        raise SystemExit(f"STOP: unexpected polling anchor: {signature}")
    return text[:start] + body.replace(old, new, 1) + text[end:]


def patched_sources(root):
    directory = root / "lib/radio/zmq"
    rx = directory / "radio_zmq_rx_channel.cpp"
    tx = directory / "radio_zmq_tx_channel.cpp"
    rx_text = rx.read_text()
    tx_text = tx.read_text()

    old = """    if (err == EFSM || err == EAGAIN) {
      // Ignore timeout and FSM error.
      return;
    }"""
    new = """    if (err == EFSM || err == EAGAIN) {
      // Experimental scheduling hint only when no data is available.
      if (err == EAGAIN) {
        std::this_thread::yield();
      }
      return;
    }"""
    rx_text = patch_function(
        rx_text, "void radio_zmq_rx_channel::receive_response()",
        old, new,
    )

    old = """      if (err == EFSM || err == EAGAIN) {
        // Ignore timeout and FSM error.
      }"""
    new = """      if (err == EFSM || err == EAGAIN) {
        // Experimental scheduling hint only when no request is available.
        if (err == EAGAIN) {
          std::this_thread::yield();
        }
      }"""
    tx_text = patch_function(
        tx_text, "void radio_zmq_tx_channel::receive_request()",
        old, new,
    )

    old = """  if (count == 0) {
    return;
  }"""
    new = """  if (count == 0) {
    std::this_thread::yield();
    return;
  }"""
    tx_text = patch_function(
        tx_text, "void radio_zmq_tx_channel::send_response()",
        old, new,
    )
    return {rx: rx_text, tx: tx_text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    updates = patched_sources(args.source_root)
    if args.check:
        print("PASS: all polling anchors matched; no source changes.")
        return
    for path, text in updates.items():
        path.write_text(text)
        print(f"Patched: {path}")


if __name__ == "__main__":
    main()
