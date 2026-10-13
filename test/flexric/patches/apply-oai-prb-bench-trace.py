#!/usr/bin/env python3
"""Record actual scheduler-generated PDSCH grants in Docker's benchmark copy."""
from pathlib import Path

def transform(text):
    old = """        if (sched_rsp->DL_req.dl_tti_request_body.dl_tti_pdu_list[p].PDUType == NFAPI_NR_DL_TTI_PDSCH_PDU_TYPE)
          n_pdsch++;"""
    new = r"""        if (sched_rsp->DL_req.dl_tti_request_body.dl_tti_pdu_list[p].PDUType == NFAPI_NR_DL_TTI_PDSCH_PDU_TYPE) {
          n_pdsch++;
          const nfapi_nr_dl_tti_pdsch_pdu_rel15_t *grant =
              &sched_rsp->DL_req.dl_tti_request_body.dl_tti_pdu_list[p].pdsch_pdu.pdsch_pdu_rel15;
          printf("PRB_GRANT {\"iteration\":%d,\"frame\":%d,\"slot\":%d,"
                 "\"rnti\":%u,\"bwp_start\":%u,\"bwp_size\":%u,"
                 "\"rb_start\":%u,\"rb_size\":%u,\"tb_bytes\":%u}\n",
                 dl_iter, frame, slot, (unsigned)grant->rnti,
                 (unsigned)grant->BWPStart, (unsigned)grant->BWPSize,
                 (unsigned)grant->rbStart, (unsigned)grant->rbSize,
                 (unsigned)grant->TBSize[0]);
        }"""
    if text.count(old) != 1 or "PRB_GRANT " in text:
        raise RuntimeError("Unexpected benchmark trace anchor")
    return text.replace(old, new, 1)

if __name__ == "__main__":
    p = Path("/src/oai/tests/nrdlbench/dlbench.c")
    p.write_text(transform(p.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied: actual PDSCH grant tracing to Docker benchmark copy")
