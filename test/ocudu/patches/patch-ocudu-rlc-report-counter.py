#!/usr/bin/env python3
"""Preserve the matched RLC collection counter in an isolated source copy."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    target = root / "lib/rlc/rlc_bearer_metrics_collector.cpp"
    text = target.read_text()
    old = "rlc_metrics report = {du, ue, rb, {m_higher, m_lower}, m_rx_high, 0, metrics_period};"
    new = (
        "rlc_metrics report = "
        "{du, ue, rb, {m_higher, m_lower}, m_rx_high, m_lower.counter, metrics_period};"
    )
    if text.count(old) != 1:
        raise SystemExit("STOP: unexpected RLC report counter anchor")
    if args.check:
        print("PASS: RLC counter anchor matched; no source changes.")
        return
    if any((p / ".git").exists() for p in (root, *root.parents)):
        raise SystemExit("STOP: apply only to an isolated source copy outside Git.")
    target.write_text(text.replace(old, new, 1))
    print(f"Patched: {target}")


if __name__ == "__main__":
    main()
