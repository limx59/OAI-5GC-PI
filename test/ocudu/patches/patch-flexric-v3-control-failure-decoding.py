#!/usr/bin/env python3
"""Enable bounded E2AP V3 Control Failure decoding in a build copy."""
import argparse
from pathlib import Path

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected anchor: " + old[:100])
    return text.replace(old, new, 1)

def transform(root):
    name = "src/lib/e2ap/v3_01/dec/e2ap_msg_dec_asn.c"
    text = (root / name).read_text()
    anchor = "e2ap_msg_t e2ap_dec_control_failure("
    if text.count(anchor) != 1:
        raise RuntimeError("Unexpected decoder definition")
    start = text.index(anchor)
    end = text.index("\n}", start) + 2
    section = text[start:end]
    section = once(
        section, '  assert(0!=0 && "Untested code");',
        "  // Laboratory Control Failure path; retain field validation.",
    )
    section = once(
        section,
        "  const RICcontrolFailure_t* out = &pdu->choice.unsuccessfulOutcome->value.choice.RICcontrolFailure;",
        """  const RICcontrolFailure_t* out = &pdu->choice.unsuccessfulOutcome->value.choice.RICcontrolFailure;
  assert(out->protocolIEs.list.count >= 3 &&
         out->protocolIEs.list.count <= 6);
  bool lab_control_cause_present = false;
  for (int i = 0; i < out->protocolIEs.list.count; ++i) {
    assert(out->protocolIEs.list.array[i] != NULL);
    for (int j = 0; j < i; ++j) {
      assert(out->protocolIEs.list.array[i]->id !=
             out->protocolIEs.list.array[j]->id);
    }
  }""",
    )
    section = once(
        section,
        "      cf->cause = copy_cause(cf_ie->value.choice.Cause);",
        """      cf->cause = copy_cause(cf_ie->value.choice.Cause);
      lab_control_cause_present = true;""",
    )
    section = once(
        section, "  return ret;",
        "  assert(lab_control_cause_present);\n  return ret;",
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
