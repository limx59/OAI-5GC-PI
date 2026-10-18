#!/usr/bin/env python3
"""Wire the optional gNB KPM clock to DRB RLC metric timers."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def add_field(text, anchor, ending):
    if text.count(anchor) != 1:
        raise SystemExit(f"STOP: unexpected structure: {anchor}")
    start = text.index(anchor)
    end = text.index(ending, start)
    return (
        text[:end]
        + "\n  // Optional metrics clock; protocol timers retain their existing source.\n"
        + "  timer_manager* rlc_metrics_timers = nullptr;\n"
        + text[end:]
    )


def transform(root):
    names = [
        "include/ocudu/du/du_high/du_high_configuration.h",
        "include/ocudu/du/du_high/du_manager/du_manager_params.h",
        "lib/du/du_high/du_high_impl.cpp",
        "lib/du/du_high/du_manager/converters/rlc_config_helpers.cpp",
        "lib/du/du_high/o_du_high_factory.cpp",
    ]
    texts = {name: (root / name).read_text() for name in names}
    factory = (root / "include/ocudu/rlc/rlc_factory.h").read_text()
    odu_config = (root / "include/ocudu/du/du_high/o_du_high_config.h").read_text()
    if "timer_manager* metrics_timers = nullptr;" not in factory:
        raise SystemExit("STOP: apply the RLC metrics clock patch first")
    if "kpm_wall_timers" not in odu_config:
        raise SystemExit("STOP: apply the gNB wall clock patch first")
    if any("rlc_metrics_timers" in text for text in texts.values()):
        raise SystemExit("STOP: metrics clock wiring already present")

    name = names[0]
    texts[name] = add_field(
        texts[name], "struct du_high_dependencies {", "\n};",
    )
    if '#include "ocudu/support/timers.h"' not in texts[name]:
        texts[name] = once(
            texts[name], "#pragma once",
            '#pragma once\n\n#include "ocudu/support/timers.h"',
        )

    name = names[1]
    texts[name] = add_field(
        texts[name], "  struct service_params {", "\n  };",
    )

    name = names[2]
    texts[name] = once(
        texts[name],
        "       dependencies.exec_mapper->cell_mapper()},",
        "       dependencies.exec_mapper->cell_mapper(),\n"
        "       dependencies.rlc_metrics_timers},",
    )

    name = names[3]
    texts[name] = once(
        texts[name],
        "  msg.rb_id             = bearer.drb_id;",
        "  msg.rb_id             = bearer.drb_id;\n"
        "  msg.metrics_timers    = du_services.rlc_metrics_timers;",
    )

    name = names[4]
    texts[name] = once(
        texts[name],
        "  auto du_hi = make_du_high(du_hi_cfg, odu_dependencies.du_hi);",
        """  auto du_hi_metrics_dependencies = odu_dependencies.du_hi;
  du_hi_metrics_dependencies.rlc_metrics_timers = odu_dependencies.kpm_wall_timers;
  auto du_hi = make_du_high(du_hi_cfg, du_hi_metrics_dependencies);""",
    )
    return texts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only to an isolated source copy outside Git")
    updated = transform(root)
    for name, text in updated.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCHED'}: {name}")
    print("DRB metrics clock wiring only; integration compilation and runtime tests pending.")


if __name__ == "__main__":
    main()
