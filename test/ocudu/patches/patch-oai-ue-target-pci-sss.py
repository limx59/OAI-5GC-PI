#!/usr/bin/env python3
"""Preserve the requested target PCI during SSS search in a build copy."""
import argparse
from pathlib import Path


def transform(root):
    name = "openair1/PHY/NR_UE_TRANSPORT/nr_initial_sync.c"
    path = root / name
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise RuntimeError("Missing or unexpected source")
    text = path.read_text()
    old = "params->sss_res = rx_sss_nr(&p_sss, pss_res, -1, rxdataF);"
    new = (
        "params->sss_res = rx_sss_nr("
        "&p_sss, pss_res, params->target_nid_cell, rxdataF);"
    )
    if text.count(old) != 1:
        raise RuntimeError("Unexpected SSS call anchor")
    return {name: text.replace(old, new, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only to an isolated build copy")
    for name, text in transform(root).items():
        if not args.check:
            (root / name).write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ") + name)


if __name__ == "__main__":
    main()
