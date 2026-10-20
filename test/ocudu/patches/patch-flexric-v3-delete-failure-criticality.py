#!/usr/bin/env python3
"""Align V3 delete-failure Cause criticality with the ASN.1 definition."""

import argparse
from pathlib import Path


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"STOP: unexpected anchor: {old!r}")
    return text.replace(old, new, 1)


def edit_function(text, signature, change):
    if text.count(signature) != 1:
        raise SystemExit(f"STOP: unexpected function: {signature}")
    start = text.index(signature)
    end = text.find("\n}", start)
    if end < 0:
        raise SystemExit("STOP: missing function end")
    end += 2
    return text[:start] + change(text[start:end]) + text[end:]


def transform(root):
    enc = "src/lib/e2ap/v3_01/enc/e2ap_msg_enc_asn.c"
    dec = "src/lib/e2ap/v3_01/dec/e2ap_msg_dec_asn.c"
    e = (root / enc).read_text()
    d = (root / dec).read_text()

    def fix_encoder(body):
        if "act_not_adm->id = ProtocolIE_ID_id_Cause;" not in body:
            raise SystemExit("STOP: apply the V3 failure-encoding patch first")
        return once(
            body,
            "act_not_adm->criticality = Criticality_reject;",
            "act_not_adm->criticality = Criticality_ignore;",
        )

    def fix_decoder(body):
        if "// Validate mandatory delete-failure IEs" not in body:
            raise SystemExit("STOP: apply the delete-failure decoding patch first")
        return once(
            body,
            "assert(act_not_adm->criticality == Criticality_reject);",
            "assert(act_not_adm->criticality == Criticality_ignore);",
        )

    e = edit_function(
        e,
        "E2AP_PDU_t* e2ap_enc_subscription_delete_failure_asn_pdu(",
        fix_encoder,
    )
    d = edit_function(
        d,
        "e2ap_msg_t e2ap_dec_subscription_delete_failure(",
        fix_decoder,
    )
    return {enc: e, dec: d}


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
    updates = transform(root)
    for name, text in updates.items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("Delete-failure Cause criticality only; compilation and tests pending.")


if __name__ == "__main__":
    main()
