#!/usr/bin/env python3
"""Experimental NCC wrap handling; applies only to Docker's OAI copy."""
from pathlib import Path

SYNC = r"""static void nr_sync_nh_chain(const uint8_t kamf[SECURITY_KEY_LEN],
                             uint8_t kgnb[SECURITY_KEY_LEN],
                             uint8_t nh[SECURITY_KEY_LEN],
                             uint64_t *nhcc,
                             const int8_t target_ncc)
{
  AssertFatal(target_ncc >= 0 && target_ncc <= 7,
              "NCC outside three-bit range\n");
  /* Keep a cumulative local count; the received NCC carries its low 3 bits.
   * Initial zero is therefore distinct from the eighth NH derivation. */
  const uint64_t steps = ((uint64_t)target_ncc + 8 - (*nhcc & 7)) & 7;
  if (steps == 0)
    return;
  const uint64_t target_count = *nhcc + steps;
  LOG_I(NR_RRC, "NCC synchronization: local count=%lu, received=%d, steps=%lu\n",
        *nhcc, target_ncc, steps);
  if (*nhcc == 0) {
    /* Preserve the existing laboratory initial NAS COUNT convention. */
    derive_kgnb(kamf, 0, kgnb);
    nr_derive_nh(kamf, kgnb, nh);
    *nhcc = 1;
  }
  while (*nhcc < target_count) {
    nr_derive_nh(kamf, nh, nh);
    ++*nhcc;
  }
}
"""

UPDATE = r"""static void nr_update_kgnb_from_ncc(NR_UE_RRC_INST_t *rrc,
                                    const uint8_t kamf[SECURITY_KEY_LEN],
                                    int8_t received_ncc)
{
  AssertFatal(received_ncc >= 0 && received_ncc <= 7,
              "NCC outside three-bit range\n");
  if ((uint64_t)received_ncc == (rrc->nhcc & 7)) {
    RRCLOG_D("NCC values match (%d), using horizontal derivation\n", received_ncc);
    nr_derive_kgnb_horizontal(rrc->phyCellID, rrc->arfcn_ssb, rrc->kgnb);
  } else {
    nr_sync_nh_chain(kamf, rrc->kgnb, rrc->nh, &rrc->nhcc, received_ncc);
    nr_derive_kgnb_vertical(rrc->phyCellID, rrc->arfcn_ssb, rrc->kgnb, rrc->nh);
  }
}
"""

def replace_function(text, name, replacement):
    anchor = "static void " + name + "("
    if text.count(anchor) != 1:
        raise RuntimeError("Unexpected function anchor: " + name)
    start = text.index(anchor)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[:start] + replacement.rstrip() + text[index + 1:]
    raise RuntimeError("Unclosed function: " + name)

def transform(text):
    if "NCC synchronization: local count=" in text:
        raise RuntimeError("NCC wrap patch already applied")
    for anchor in (
        "NH chain should only increase",
        "if (target_ncc <= *nhcc)",
        "rrc->nhcc = received_ncc;",
    ):
        if text.count(anchor) != 1:
            raise RuntimeError("Unexpected original implementation: " + anchor)
    text = replace_function(text, "nr_sync_nh_chain", SYNC)
    return replace_function(text, "nr_update_kgnb_from_ncc", UPDATE)

def main():
    sdk = Path("/src/oai")
    if not sdk.is_dir():
        raise SystemExit("Only Docker OAI copy /src/oai is supported.")
    p = sdk / "openair2/RRC/NR_UE/rrc_UE.c"
    updated = transform(p.read_text(encoding="utf-8"))
    p.write_text(updated, encoding="utf-8")
    print("Applied experimental UE NCC wrap handling to Docker OAI copy.")

if __name__ == "__main__":
    main()
