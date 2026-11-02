#!/usr/bin/env python3
"""Expose decoded RC control advertisement in a Docker build copy."""
import argparse
from pathlib import Path

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)

def transform(root):
    header = root / "src/xApp/swig/swig_wrapper.h"
    source = root / "src/xApp/swig/swig_wrapper.cpp"
    h = header.read_text()
    c = source.read_text()
    h = once(h, "struct swig_ran_function_t {",
             "struct swig_ran_function_t {\n  std::string rc_definition_json;")
    c = "#include <sstream>\n" + c
    c = once(c, "      swig_ran_function_t tmp_ran;",
             """      swig_ran_function_t tmp_ran{};
      if (rf->defn.type == RC_RAN_FUNC_DEF_E) {
        const auto* control = rf->defn.rc.ctrl;
        std::ostringstream out;
        out << "{\\"control_present\\":"
            << (control != nullptr ? "true" : "false")
            << ",\\"styles\\":[";
        if (control != nullptr) {
          assert(control->sz_seq_ctrl_style <= 63);
          assert(control->sz_seq_ctrl_style == 0 ||
                 control->seq_ctrl_style != nullptr);
          for (size_t k = 0; k < control->sz_seq_ctrl_style; ++k) {
            const auto& style = control->seq_ctrl_style[k];
            assert(style.sz_seq_ctrl_act <= 65535);
            assert(style.sz_seq_ctrl_act == 0 ||
                   style.seq_ctrl_act != nullptr);
            if (k != 0) out << ",";
            out << "{\\"style_type\\":" << style.style_type
                << ",\\"header_format\\":" << style.hdr
                << ",\\"message_format\\":" << style.msg
                << ",\\"outcome_format\\":" << style.out_frmt
                << ",\\"actions\\":[";
            for (size_t a = 0; a < style.sz_seq_ctrl_act; ++a) {
              const auto& action = style.seq_ctrl_act[a];
              if (a != 0) out << ",";
              out << "{\\"id\\":" << action.id
                  << ",\\"associated_parameter_count\\":"
                  << action.sz_seq_assoc_ran_param << "}";
            }
            out << "]}";
          }
        }
        out << "]}";
        tmp_ran.rc_definition_json = out.str();
      }""")
    return {header: h, source: c}

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
    updates = transform(root)
    for path, text in updates.items():
        if not args.check:
            path.write_text(text)
        print(("CHECKED: " if args.check else "PATCHED: ")
              + str(path.relative_to(root)))

if __name__ == "__main__":
    main()
