#!/usr/bin/env python3
"""Correct KPM V3 header timestamp byte order in an isolated source copy."""

import argparse
from pathlib import Path


def transform(root):
    base = "src/sm/kpm_sm/kpm_sm_v03.00"
    updated = {}
    for name, conversion in (
        (f"{base}/enc/enc_asn/enc_ric_ind_hdr_frm_1.c", "htonl"),
        (f"{base}/dec/dec_asn/dec_ric_ind_hdr_frm_1.c", "ntohl"),
    ):
        text = (root / name).read_text()
        old = "uint64_t v = ((uint64_t)x1) << 32 | x2;"
        new = (
            "// Swap both byte order and word positions on little-endian hosts.\n"
            f"  uint64_t v = ({conversion}(1) == 1)\n"
            "      ? x : (((uint64_t)x2) << 32) | x1;"
        )
        if text.count(old) != 1:
            raise SystemExit(f"STOP: unexpected byte-order anchor: {name}")
        updated[name] = text.replace(old, new, 1)
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only outside a Git working tree")
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("KPM V3 timestamp codec only; compilation and runtime tests pending.")


if __name__ == "__main__":
    main()
