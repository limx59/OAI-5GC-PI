#!/usr/bin/env python3
"""Apply a bounded PRB execution adapter only to Docker's FlexRIC copy."""
from pathlib import Path

HANDLER = '\nsm_ag_if_ans_t write_ctrl_slice_sm(void const* data)\n{\n  sm_ag_if_ans_t ans = {.type = CTRL_OUTCOME_SM_AG_IF_ANS_V0};\n  ans.ctrl_out.type = SLICE_AGENT_IF_CTRL_ANS_V0;\n  ans.ctrl_out.slice.ans = SLICE_CTRL_OUT_ERROR;\n  if (data == NULL)\n    return ans;\n  const slice_ctrl_req_data_t *request = data;\n  const slice_ctrl_msg_t *msg = &request->msg;\n  if (msg->type != SLICE_CTRL_SM_V0_ADD)\n    return ans;\n  const ul_dl_slice_conf_t *dl = &msg->u.add_mod_slice.dl;\n  if (dl->len_slices != 3 || dl->slices == NULL\n      || msg->u.add_mod_slice.ul.len_slices != 0)\n    return ans;\n\n  int quotas[3] = {-1, -1, -1};\n  for (unsigned i = 0; i < 3; ++i) {\n    const fr_slice_t *slice = &dl->slices[i];\n    if (slice->id > 2 || quotas[slice->id] != -1\n        || slice->params.type != SLICE_ALG_SM_V0_NVS\n        || slice->params.u.nvs.conf != SLICE_SM_NVS_V0_CAPACITY)\n      return ans;\n    double percentage = 100.0 * slice->params.u.nvs.u.capacity.u.pct_reserved;\n    if (!isfinite(percentage) || percentage < 0 || percentage > 100)\n      return ans;\n    int q = (int)(percentage + 0.5);\n    if (fabs(percentage - q) > 0.0001)\n      return ans;\n    quotas[slice->id] = q;\n  }\n  if (quotas[0] + quotas[1] + quotas[2] != 100)\n    return ans;\n\n  char values[3][8];\n  for (int i = 0; i < 3; ++i)\n    snprintf(values[i], sizeof(values[i]), "%d", quotas[i]);\n  char *argv[] = {"/usr/bin/python3", "/opt/oai-pi/execute-oai-prb-control.py",\n                  values[0], values[1], values[2], NULL};\n  pid_t child;\n  printf("[E2 Agent]: SLICE CONTROL ADD rx; executing NR PRB simulation\\n");\n  fflush(stdout);\n  int rc = posix_spawn(&child, argv[0], NULL, NULL, argv, environ);\n  if (rc != 0)\n    return ans;\n  int status;\n  pid_t waited;\n  do {\n    waited = waitpid(child, &status, 0);\n  } while (waited < 0 && errno == EINTR);\n  if (waited == child && WIFEXITED(status) && WEXITSTATUS(status) == 0)\n    ans.ctrl_out.slice.ans = SLICE_CTRL_OUT_OK;\n  return ans;\n}\n'

def transform(text):
    start = text.index("sm_ag_if_ans_t write_ctrl_slice_sm(void const* data)")
    if text.count("sm_ag_if_ans_t write_ctrl_slice_sm(") != 1:
        raise RuntimeError("Unexpected slice handler")
    if text[start:].strip()[-1:] != "}":
        raise RuntimeError("Unexpected trailing source")
    includes = """
#include <errno.h>
#include <math.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
"""
    text = text[:start] + HANDLER
    text = includes + text
    old = "  fill_slice_ind_data(slice);\n  return true;"
    if text.count(old) != 1:
        raise RuntimeError("Unexpected synthetic indication anchor")
    text = text.replace(old, "  (void)slice;\n  return false;", 1)
    return text

if __name__ == "__main__":
    p = Path("/src/flexric/examples/emulator/agent/sm_slice.c")
    p.write_text(transform(p.read_text()), encoding="utf-8")
    print("Applied: E2-controlled independent NR scheduler execution")
