"""Extract one laboratory UE identity from current-run OCUDU logs."""
import re


def require(value, message):
    if not value:
        raise RuntimeError(message)


def extract_identity(gnb_log, ue_log):
    # Docker timestamps are transport prefixes, not part of ASN.1 fields.
    lines = [
        re.sub(r"^\d{4}-\d\d-\d\dT\S+\s+", "", line)
        for line in gnb_log.splitlines()
    ]
    contexts = []
    header = re.compile(
        r"\[NGAP\s*\].*Rx PDU ue=(\d+) ran_ue=(\d+) amf_ue=(\d+): "
        r"InitialContextSetupRequest"
    )
    for index, line in enumerate(lines):
        match = header.search(line)
        if not match:
            continue
        following = []
        for item in lines[index + 1:index + 250]:
            if re.search(r"\[NGAP\s*\].*(?:Rx|Tx) PDU", item):
                break
            following.append(item)
        block = "\n".join(following)
        guamis = re.findall(
            r'"pLMNIdentity"\s*:\s*"([0-9a-fA-F]{6})"\s*,\s*'
            r'"aMFRegionID"\s*:\s*"([01]{8})"\s*,\s*'
            r'"aMFSetID"\s*:\s*"([01]{10})"\s*,\s*'
            r'"aMFPointer"\s*:\s*"([01]{6})"',
            block,
        )
        require(len(guamis) == 1, "Expected one context-request GUAMI")
        contexts.append((tuple(map(int, match.groups())), guamis[0]))
    require(len(contexts) == 1, "Expected one InitialContextSetupRequest")
    (ue, ran_ue, amf_ue), guami = contexts[0]
    require(guami[0].lower() == "00f110", "Unexpected laboratory PLMN")
    require(0 <= amf_ue < (1 << 40), "Invalid AMF UE identity")

    f1 = set()
    for line in lines:
        if "[CU-CP-F1" not in line or "Added UE context" not in line:
            continue
        match = re.search(r"\bue=(\d+) du_ue=(\d+) cu_ue=(\d+):", line)
        if match:
            f1.add(tuple(map(int, match.groups())))
    require(len(f1) == 1, "Expected one source F1AP UE context")
    f1_ue, du_f1ap, cu_f1ap = next(iter(f1))
    require(f1_ue == ue, "NGAP and F1AP UE indexes differ")
    require(0 <= cu_f1ap <= 0xffffffff, "Invalid CU F1AP identity")

    sync = re.findall(r"Initial sync successful, PCI:\s*(\d+)", ue_log)
    require(sync == ["1"], "Expected one initial synchronization on PCI 1")
    changes = re.findall(r"phyCellID\s+(\d+)->(\d+)", ue_log)
    require(changes and all(int(target) == 1 for _, target in changes),
            "Unexpected source serving-cell history")
    require("RICcontrolRequest" not in gnb_log
            and "Received RIC Control Request" not in gnb_log,
            "Control already present before identity extraction")
    return {
        "ue_index": ue,
        "ran_ue_id": ran_ue,
        "amf_ue_id": amf_ue,
        "cu_f1ap_id": cu_f1ap,
        "du_f1ap_id": du_f1ap,
        "plmn_hex": guami[0].lower(),
        "amf_region": int(guami[1], 2),
        "amf_set": int(guami[2], 2),
        "amf_pointer": int(guami[3], 2),
        "source_pci": 1,
        "source_nci": 107520,
        "target_pci": 2,
        "target_nci": 107521,
        "target_cgi_hex": "0000f11000001a4010",
    }
