#!/usr/bin/env python3
"""Copy optional KPM granularity scalars without array traversal."""

import argparse
from pathlib import Path


def transform(text):
    for source, target, indent in (
        ("msg", "swig_data.msg.frm_1", "    "),
        ("meas_ue->ind_msg_format_1", "tmp.ind_msg_format_1", "      "),
    ):
        old = "\n".join(indent + line for line in (
            "size_t idx = 0;",
            f"if ({source}->gran_period_ms) {{",
            f"  while ({source}->gran_period_ms[idx]) {{",
            f"    {target}.gran_period_ms.push_back({source}->gran_period_ms[idx]);",
            "    idx++;",
            "  }",
            "}",
        )) if source == "msg" else "\n".join(indent + line for line in (
            "size_t idx = 0;",
            f"if ({source}.gran_period_ms) {{",
            f"  while ({source}.gran_period_ms[idx]) {{",
            f"    {target}.gran_period_ms.push_back({source}.gran_period_ms[idx]);",
            "    idx++;",
            "  }",
            "}",
        ))
        access = (
            f"{source}->gran_period_ms" if source == "msg"
            else f"{source}.gran_period_ms"
        )
        new = "\n".join(indent + line for line in (
            "// Optional granularity is one scalar, not a terminated array.",
            f"if ({access} != nullptr) {{",
            f"  {target}.gran_period_ms.push_back(*{access});",
            "}",
        ))
        if text.count(old) != 1:
            raise SystemExit(f"STOP: unexpected granularity anchor: {target}")
        text = text.replace(old, new, 1)
    return text


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
    path = root / "src/xApp/swig/swig_wrapper.cpp"
    updated = transform(path.read_text())
    if not args.check:
        path.write_text(updated)
    print(f"{'CHECK' if args.check else 'PATCH'}: src/xApp/swig/swig_wrapper.cpp")
    print("Optional KPM scalar copies only; compilation and runtime tests pending.")


if __name__ == "__main__":
    main()
