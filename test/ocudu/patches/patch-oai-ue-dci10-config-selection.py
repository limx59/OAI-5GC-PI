#!/usr/bin/env python3
"""Select DCI 1_0 configuration per grant rather than pending SI state."""
import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)


def transform(root):
    name = "openair2/LAYER2/NR_MAC_UE/nr_ue_procedures.c"
    path = root / name
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise RuntimeError("Missing or unexpected source")
    text = path.read_text()
    anchor = "static int nr_ue_process_dci_dl_10("
    if text.count(anchor) != 1:
        raise RuntimeError("Unexpected DCI 1_0 definition")
    start = text.index(anchor)
    end = text.index("\n}", start) + 2
    section = text[start:end]

    # Scope all three SIB1-dependent decisions to the current SI-RNTI grant.
    if section.count("mac->get_sib1") != 3:
        raise RuntimeError("Unexpected SIB1-dependent decision count")
    section = section.replace("mac->get_sib1", "is_sib1")
    section = once(
        section,
        "  NR_PDSCH_Config_t *pdsch_config =",
        "  const bool is_sib1 = "
        "(rnti_type == TYPE_SI_RNTI_) && mac->get_sib1;\n"
        "  NR_PDSCH_Config_t *pdsch_config =",
    )

    # The dedicated configuration remains optional.
    section = once(
        section,
        "      && pdsch_config->dataScramblingIdentityPDSCH)",
        "      && pdsch_config\n"
        "      && pdsch_config->dataScramblingIdentityPDSCH)",
    )
    return {name: text[:start] + section + text[end:]}


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
