#!/usr/bin/env python3
"""Expose parsed testmode state in the laboratory validated dry-run image."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    root = args.source_root.resolve()
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise RuntimeError("Apply only to Docker build source")
    path = root / "apps/gnb/gnb.cpp"
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise RuntimeError("Missing gNB source")
    text = path.read_text()
    anchor = '    fmt::println("LAB_CONFIG_VALIDATION_PASSED");\n'
    if text.count(anchor) != 1:
        raise RuntimeError("Expected validated dry-run marker exactly once")
    addition = """    fmt::println(
        "LAB_TESTMODE_STATE du_enabled={} du_rnti={} cu_up_enabled={} no_core={}",
        o_du_app_unit->get_o_du_high_unit_config().du_high_cfg.config.is_testmode_enabled(),
        static_cast<unsigned>(
            o_du_app_unit->get_o_du_high_unit_config().du_high_cfg.config.test_mode_cfg.test_ue.rnti),
        o_cu_up_app_unit->get_o_cu_up_unit_config().cu_up_cfg.test_mode_cfg.enabled,
        o_cu_cp_app_unit->get_o_cu_cp_unit_config().cucp_cfg.amf_config.no_core);
"""
    updated = text.replace(anchor, addition + anchor, 1)
    if not (
        updated.index("!o_du_app_unit->on_configuration_validation()")
        < updated.index("LAB_TESTMODE_STATE")
        < updated.index("LAB_CONFIG_VALIDATION_PASSED")
        < updated.index("  // Set up logging.")
    ):
        raise RuntimeError("Unexpected validation/initialization order")
    path.write_text(updated)
    print("PATCHED: parsed state output before dry-run exit")


if __name__ == "__main__":
    main()
