#!/usr/bin/env python3
"""Complete E2AP V3 subscription failure encoding in an isolated copy."""

import argparse
from pathlib import Path
import re


def function_span(text, name):
    pattern = (
        r"(?m)^E2AP_PDU_t\*\s+" + re.escape(name)
        + r"\s*\([^;{}]*\)\s*\{"
    )
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise SystemExit(f"STOP: unexpected function: {name}")
    start = matches[0].start()
    end = text.find("\n}", matches[0].end())
    if end < 0:
        raise SystemExit(f"STOP: missing function end: {name}")
    return start, end + 2


DIAGNOSTICS = r"""
// Encode owned ASN.1 diagnostics without borrowing internal pointers.
static CriticalityDiagnostics_t oai_pi_encode_failure_diagnostics(
    criticality_diagnostics_t const* source)
{
  assert(source != NULL);
  CriticalityDiagnostics_t out = {0};
  if (source->procedure_code != NULL) {
    out.procedureCode = calloc(1, sizeof(*out.procedureCode));
    assert(out.procedureCode != NULL);
    *out.procedureCode = *source->procedure_code;
  }
  if (source->trig_msg != NULL) {
    assert(*source->trig_msg >= INITIATING_MESSAGE &&
           *source->trig_msg <= UNSUCCESSFUL_OUTCOME);
    out.triggeringMessage = calloc(1, sizeof(*out.triggeringMessage));
    assert(out.triggeringMessage != NULL);
    *out.triggeringMessage = *source->trig_msg;
  }
  if (source->proc_crit != NULL) {
    assert(*source->proc_crit >= REJECT && *source->proc_crit <= NOTIFY);
    out.procedureCriticality = calloc(1, sizeof(*out.procedureCriticality));
    assert(out.procedureCriticality != NULL);
    *out.procedureCriticality = *source->proc_crit;
  }
  if (source->req_id != NULL) {
    out.ricRequestorID = calloc(1, sizeof(*out.ricRequestorID));
    assert(out.ricRequestorID != NULL);
    out.ricRequestorID->ricRequestorID = source->req_id->ric_req_id;
    out.ricRequestorID->ricInstanceID = source->req_id->ric_inst_id;
  }
  if (source->len_ie > 0) {
    assert(source->ie != NULL);
    out.iEsCriticalityDiagnostics =
        calloc(1, sizeof(*out.iEsCriticalityDiagnostics));
    assert(out.iEsCriticalityDiagnostics != NULL);
    for (size_t i = 0; i < source->len_ie; ++i) {
      ie_criticality_diagnostics_t const* item = &source->ie[i];
      assert(item->crit >= REJECT && item->crit <= NOTIFY);
      assert(item->type == NOT_UNDERSTOOD || item->type == MISSING);
      CriticalityDiagnostics_IE_Item_t* encoded = calloc(1, sizeof(*encoded));
      assert(encoded != NULL);
      encoded->iECriticality = item->crit;
      encoded->iE_ID = item->id;
      encoded->typeOfError = item->type;
      int rc = ASN_SEQUENCE_ADD(
          &out.iEsCriticalityDiagnostics->list, encoded);
      assert(rc == 0);
    }
  }
  return out;
}

"""


def transform(root):
    name = "src/lib/e2ap/v3_01/enc/e2ap_msg_enc_asn.c"
    text = (root / name).read_text()
    if "oai_pi_encode_failure_diagnostics" in text:
        raise SystemExit("STOP: encoding patch already present")

    delete_name = "e2ap_enc_subscription_delete_failure_asn_pdu"
    start, end = function_span(text, delete_name)
    deletion = text[start:end]

    old = "act_not_adm->id = ProtocolIE_ID_id_RICactions_NotAdmitted;"
    if deletion.count(old) != 1:
        raise SystemExit("STOP: unexpected delete-failure Cause anchor")
    deletion = deletion.replace(
        old, "act_not_adm->id = ProtocolIE_ID_id_Cause;", 1)

    optional = r"""
  // Criticality Diagnostics. Optional.
  if (df->crit_diag != NULL) {
    RICsubscriptionDeleteFailure_IEs_t* diagnostic =
        calloc(1, sizeof(*diagnostic));
    assert(diagnostic != NULL);
    diagnostic->id = ProtocolIE_ID_id_CriticalityDiagnostics;
    diagnostic->criticality = Criticality_ignore;
    diagnostic->value.present =
        RICsubscriptionDeleteFailure_IEs__value_PR_CriticalityDiagnostics;
    diagnostic->value.choice.CriticalityDiagnostics =
        oai_pi_encode_failure_diagnostics(df->crit_diag);
    rc = ASN_SEQUENCE_ADD(&out->protocolIEs.list, diagnostic);
    assert(rc == 0);
  }
  return pdu;"""
    pattern = (
        r"\n[ \t]*// Criticality Diagnosis\. Optional"
        r"[\s\S]*?\n[ \t]*return pdu;"
    )
    deletion, count = re.subn(
        pattern, lambda _: optional, deletion)
    if count != 1:
        raise SystemExit("STOP: unexpected optional diagnostics block")

    subscription = deletion.replace(
        delete_name, "e2ap_enc_subscription_failure_asn_pdu"
    ).replace(
        "ric_subscription_delete_failure_t", "ric_subscription_failure_t"
    ).replace(
        "RICsubscriptionDelete", "RICsubscription"
    )
    subscription = re.sub(r"\bdf\b", "sf", subscription)

    text = text[:start] + deletion + text[end:]
    start, end = function_span(text, "e2ap_enc_subscription_failure_asn_pdu")
    if 'assert(0!=0 && "Not implemented");' not in text[start:end]:
        raise SystemExit("STOP: expected unimplemented subscription encoder")
    text = text[:start] + DIAGNOSTICS + subscription + text[end:]

    anchor = '#include "CriticalityDiagnostics.h"'
    if text.count(anchor) != 1:
        raise SystemExit("STOP: unexpected diagnostics include")
    text = text.replace(
        anchor,
        anchor + '\n#include "CriticalityDiagnostics-IE-Item.h"'
        '\n#include "CriticalityDiagnostics-IE-List.h"'
        '\n#include "RICrequestID.h"',
        1,
    )
    return {name: text}


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
    for name, text in transform(root).items():
        if not args.check:
            (root / name).write_text(text)
        print(f"{'CHECK' if args.check else 'PATCH'}: {name}")
    print("V3 encoding only; diagnostic decoding and behavior tests pending.")


if __name__ == "__main__":
    main()
