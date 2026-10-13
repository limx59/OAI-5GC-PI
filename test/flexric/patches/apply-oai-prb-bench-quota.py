#!/usr/bin/env python3
"""Apply experimental slice caps only to Docker's NR benchmark copy."""
from pathlib import Path

POLICY = '\n/* Experimental benchmark-only hard caps, including retransmissions.\n * No borrowing between slices. Actual CCE/PUCCH and VRB commit are retained. */\nstatic int bench_quota[3];\nstatic bool bench_quota_enabled;\n\nstatic void bench_init_quota(void)\n{\n  const char *value = getenv("OAI_PRB_QUOTAS");\n  if (!value)\n    return;\n  int a, b, c, consumed = 0;\n  int count = sscanf(value, "%d,%d,%d%n", &a, &b, &c, &consumed);\n  AssertFatal(count == 3 && value[consumed] == \'\\0\'\n              && a >= 0 && a <= 100 && b >= 0 && b <= 100\n              && c >= 0 && c <= 100 && a + b + c == 100,\n              "OAI_PRB_QUOTAS must contain three percentages summing to 100\\n");\n  bench_quota[0] = a;\n  bench_quota[1] = b;\n  bench_quota[2] = c;\n  bench_quota_enabled = true;\n}\n\nstatic int bench_prb_alloc(const nr_dl_sched_params_t *params,\n                           nr_dl_candidate_t *candidates, int n_candidates)\n{\n  if (!bench_quota_enabled)\n    return nr_dl_proportional_fair(params, candidates, n_candidates);\n  AssertFatal(params->num_beams == 1, "Quota benchmark requires one beam\\n");\n  int available = params->n_rb_avail[0];\n  int cap[3], used[3] = {0};\n  for (int s = 0; s < 3; ++s)\n    cap[s] = available * bench_quota[s] / 100;\n  int scheduled = 0;\n\n  /* Retransmissions first; defer if the exact grant exceeds the slice cap. */\n  for (int phase = 0; phase < 2; ++phase) {\n    for (int i = 0; i < n_candidates; ++i) {\n      nr_dl_candidate_t *cand = &candidates[i];\n      if (cand->skipped || cand->scheduled\n          || cand->is_retx != (phase == 0))\n        continue;\n      if (cand->nssai.sst != 1 || cand->nssai.sd < 1 || cand->nssai.sd > 3)\n        continue;\n      int s = cand->nssai.sd - 1;\n      int remaining = cap[s] - used[s];\n      int minimum = cand->is_retx ? cand->retx_rbSize : 5;\n      int maximum = cand->is_retx ? minimum : remaining;\n      if (minimum <= 0 || remaining < minimum\n          || scheduled >= params->max_num_ue)\n        continue;\n      maximum = maximum < cand->bwp_size ? maximum : cand->bwp_size;\n      int start, size;\n      if (!get_rb_alloc(minimum, maximum, cand->bwp_start, cand->bwp_size,\n                        params->vrb_map[cand->alloc_beam_idx],\n                        cand->alloc_slbitmap, &start, &size))\n        continue;\n      if (cand->is_retx)\n        size = minimum;\n      cand->sched_pdsch.alloc_type = PDSCH_TYPE1;\n      cand->sched_pdsch.rbStart = start;\n      cand->sched_pdsch.rbSize = size;\n      if (!commit_alloc(params, cand))\n        continue;\n      cand->scheduled = true;\n      used[s] += size;\n      ++scheduled;\n      AssertFatal(used[s] <= cap[s], "Slice PRB cap exceeded\\n");\n    }\n  }\n  printf("PRB_POLICY {\\"frame\\":%d,\\"slot\\":%d,\\"available\\":%d,"\n         "\\"caps\\":[%d,%d,%d],\\"used\\":[%d,%d,%d]}\\n",\n         params->frame, params->slot, available,\n         cap[0], cap[1], cap[2], used[0], used[1], used[2]);\n  return scheduled;\n}\n'

def transform(text):
    changes = (
        ("/* ── Main ── */", POLICY + "\n/* ── Main ── */"),
        ("  logInit();", "  bench_init_quota();\n  logInit();"),
        ("  gNB_mac->dl_rb_alloc = nr_dl_proportional_fair;",
         "  gNB_mac->dl_rb_alloc = bench_prb_alloc;"),
        ("    sc->dl_max_mcs = bench_target_mcs;",
         """    sc->dl_max_mcs = bench_target_mcs;
    /* Three laboratory slices, assigned to real scheduler LC metadata. */
    for (int j = 0; j < seq_arr_size(&sc->lc_config); ++j) {
      nr_lc_config_t *lc = seq_arr_at(&sc->lc_config, j);
      if (lc->lcid >= 4)
        lc->nssai = (nssai_t){1, (u % 3) + 1};
    }"""),
    )
    if "static int bench_prb_alloc" in text:
        raise RuntimeError("Quota patch already applied")
    for old, new in changes:
        if text.count(old) != 1:
            raise RuntimeError("Unexpected quota anchor: " + old)
        text = text.replace(old, new, 1)
    return text

if __name__ == "__main__":
    p = Path("/src/oai/tests/nrdlbench/dlbench.c")
    p.write_text(transform(p.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied: benchmark-only slice PRB caps")
