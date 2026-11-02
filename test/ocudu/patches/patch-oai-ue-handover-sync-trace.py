#!/usr/bin/env python3
"""Add laboratory handover synchronization diagnostics in a build copy."""
import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected source anchor: " + old[:100])
    return text.replace(old, new, 1)


def transform(root):
    name = "openair1/PHY/NR_UE_TRANSPORT/nr_initial_sync.c"
    path = root / name
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise RuntimeError("Missing or unexpected source")
    text = path.read_text()

    old = "    params->sss_res = rx_sss_nr(&p_sss, pss_res, -1, rxdataF);"
    new = old + r"""
    if (params->target_nid_cell >= 0) {
      LOG_W(PHY,
            "LAB_HO_SSS target=%d pss_nid2=%d pss_pos=%d "
            "pss_peak_db=%d pss_avg_db=%d sss_ok=%d detected_pci=%d\n",
            (int)params->target_nid_cell,
            (int)pss_res->nid2,
            (int)pss_res->pos,
            (int)pss_res->peak,
            (int)pss_res->avg,
            (int)params->sss_res.success,
            (int)params->sss_res.nid_cell);
    }
"""
    text = once(text, old, new)

    old = "    if (ssbInfo->syncRes.cell_detected) {\n      uint32_t rsrp_avg"
    new = r"""    if (ssbInfo->targetNidCell >= 0) {
      LOG_W(PHY,
            "LAB_HO_PBCH target=%d detected_pci=%d "
            "ssb_start_sc=%d pbch_ok=%d\n",
            (int)ssbInfo->targetNidCell,
            (int)ssbInfo->nidCell,
            (int)ssbInfo->gscnInfo.ssbFirstSC,
            (int)ssbInfo->syncRes.cell_detected);
    }
    if (ssbInfo->syncRes.cell_detected) {
      uint32_t rsrp_avg"""
    text = once(text, old, new)
    return {name: text}


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
    outputs = transform(root)
    for name, text in outputs.items():
        if not args.check:
            (root / name).write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ") + name)


if __name__ == "__main__":
    main()
