#!/usr/bin/env python3
"""Enable V3 delete-failure mandatory-field decoding in a source copy."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def transform(root):
    name = "src/lib/e2ap/v3_01/dec/e2ap_msg_dec_asn.c"
    text = (root / name).read_text()
    start = text.index(
        "e2ap_msg_t e2ap_dec_subscription_delete_failure("
    )
    end = text.index("\n}", start) + 2
    body = text[start:end]
    marker = "// Validate mandatory delete-failure IEs before positional access."
    if marker in body:
        raise SystemExit("STOP: decoding patch already present")

    body = once(
        body,
        '  assert(0!=0 && "Untested code");',
        "  // Decode the mandatory-field path used by the rejection test.",
    )
    body = once(
        body,
        "  assert(pdu->present == E2AP_PDU_PR_unsuccessfulOutcome);",
        "  assert(pdu->present == E2AP_PDU_PR_unsuccessfulOutcome);\n"
        "  assert(pdu->choice.unsuccessfulOutcome != NULL);",
    )
    anchor = (
        "  const RICsubscriptionDeleteFailure_t* out = "
        "&pdu->choice.unsuccessfulOutcome->value.choice."
        "RICsubscriptionDeleteFailure;"
    )
    body = once(
        body, anchor,
        anchor + "\n\n  " + marker + "\n"
        "  assert(out->protocolIEs.list.count >= 3);\n"
        "  assert(out->protocolIEs.list.array != NULL);\n"
        "  for (int i = 0; i < 3; ++i) {\n"
        "    assert(out->protocolIEs.list.array[i] != NULL);\n"
        "  }",
    )
    body = once(
        body,
        "  assert(act_not_adm->id == ProtocolIE_ID_id_RICactions_NotAdmitted);",
        "  assert(act_not_adm->id == ProtocolIE_ID_id_Cause);",
    )
    return name, text[:start] + body + text[end:]


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
    name, updated = transform(root)
    if not args.check:
        (root / name).write_text(updated)
    print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("Mandatory ordered IEs only; optional diagnostics remain unsupported.")
    print("Compilation and behavior tests pending.")


if __name__ == "__main__":
    main()
