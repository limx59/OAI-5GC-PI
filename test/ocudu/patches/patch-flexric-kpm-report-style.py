#!/usr/bin/env python3
"""Select KPM action Format 1 or 4 in an isolated FlexRIC source copy."""

import argparse
from pathlib import Path


def transform(text):
    marker = "OAI_PI_KPM_REPORT_STYLE"
    if marker in text:
        raise SystemExit("STOP: report-style patch already present")

    old = "  format_action_def_e act_type = FORMAT_4_ACTION_DEFINITION; // act_def.type"
    new = """  format_action_def_e act_type = FORMAT_4_ACTION_DEFINITION;
  const char* requested_style = std::getenv("OAI_PI_KPM_REPORT_STYLE");
  if (requested_style != nullptr) {
    if (strcmp(requested_style, "1") == 0) {
      act_type = FORMAT_1_ACTION_DEFINITION;
    } else if (strcmp(requested_style, "4") != 0) {
      fprintf(stderr, "OAI_PI_KPM_REPORT_STYLE must be 1 or 4\\n");
      std::abort();
    }
  }
  printf("[xApp]: selected KPM action format = %s\\n",
         act_type == FORMAT_1_ACTION_DEFINITION ? "1" : "4");"""

    if text.count(old) != 1:
        raise SystemExit("STOP: expected exactly one action-format anchor")
    return "#include <cstdlib>\n" + text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    target = root / "src/xApp/swig/swig_wrapper.cpp"
    updated = transform(target.read_text())

    if args.check:
        print("PASS: action-format anchor matched; no source changes.")
        return

    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise SystemExit("STOP: apply only to an isolated source copy outside Git")
    target.write_text(updated)
    print(f"Patched: {target}")


if __name__ == "__main__":
    main()
