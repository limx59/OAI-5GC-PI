#!/usr/bin/env python3
"""Prepare private two-cell bridge connectivity configuration."""
import argparse
import json
from pathlib import Path
import runpy
import tempfile


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected configuration anchor: " + old)
    return text.replace(old, new, 1)


def prepare(root, output):
    root = root.resolve()
    output = output.resolve()
    if not output.is_relative_to(root) or output.exists():
        raise RuntimeError("Output exists or outside repository")
    helper = root / "test/ocudu/prepare-rc-capability.py"
    if not helper.resolve().is_relative_to(root) or not helper.is_file():
        raise RuntimeError("Missing or unexpected prerequisite")
    output.parent.mkdir(parents=True, exist_ok=True)

    # Transform a disposable private copy before creating the final directory.
    with tempfile.TemporaryDirectory(prefix="two-cell-prep-",
                                     dir=output.parent) as tmp:
        staged = Path(tmp) / "config"
        result = runpy.run_path(str(helper))["prepare"](root, staged)
        files = {p.name: p.read_text() for p in staged.iterdir() if p.is_file()}
        gnb = files["gnb-1.yml"]
        gnb = once(
            gnb,
            "  device_args: tx_port=tcp://0.0.0.0:4558,rx_port=tcp://172.22.0.161:4556",
            "  device_args: tx_port=tcp://0.0.0.0:4558,"
            "tx_port=tcp://0.0.0.0:4559,"
            "rx_port=tcp://iq-bridge:4560,rx_port=tcp://iq-bridge:4561",
        )
        gnb = once(gnb, "gnb_id: 420\n",
                   "gnb_id: 420\ngnb_id_bit_length: 28\n")
        if "\ncells:" in gnb:
            raise RuntimeError("Unexpected existing cells section")
        gnb += (
            "\ncells:\n"
            "  - pci: 1\n    sector_id: 0\n"
            "  - pci: 2\n    sector_id: 1\n"
           "    prach:\n      prach_root_sequence_index: 64\n"
           "    pdcch:\n      dedicated:\n"
           "        dci_format_0_1_and_1_1: false\n"
           "    pdsch:\n      mcs_table: qam64\n"
           "    pusch:\n      mcs_table: qam64\n"
        )
        gnb = once(
            gnb, "  all_level: info\n",
            "  all_level: info\n  ngap_level: debug\n",
        )
        files["gnb-1.yml"] = gnb
        files["ue-1.conf"] = once(
            files["ue-1.conf"],
            'rx_channels = ("tcp://172.22.0.160:4558");',
            'rx_channels = ("tcp://iq-bridge:4562");',
        )
        output.mkdir(mode=0o700)
        for name, text in files.items():
            target = output / name
            with target.open("x") as stream:
                stream.write(text)
            target.chmod(0o600)

    result.update(
        scope="Two-cell IQ bridge connectivity only",
        cells=[
            {"pci": 1, "sector_id": 0, "nr_cell_id": 107520},
            {"pci": 2, "sector_id": 1, "nr_cell_id": 107521},
        ],
        gnb_id_bit_length=28,
        target_prach_root_sequence_index=64,
        target_dci_formats="0_0_and_1_0",
        target_mcs_tables={"pdsch": "qam64", "pusch": "qam64"},
        bridge_required=True,
        radio_frame_alignment_validated=False,
        control_requests_enabled=False,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    print(json.dumps(prepare(root, args.output), indent=2))


if __name__ == "__main__":
    main()
