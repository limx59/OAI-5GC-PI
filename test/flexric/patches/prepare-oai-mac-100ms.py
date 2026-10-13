#!/usr/bin/env python3
"""Enable 100 ms MAC collection only in Docker's copied SDK and xApp."""
from pathlib import Path

def transform_sdk(text):
    old = """  } else if (strncmp(cmd, "10_ms", max_str_sz) == 0 ) {
    mac.et.ms = 10;
  } else {"""
    new = """  } else if (strncmp(cmd, "10_ms", max_str_sz) == 0 ) {
    mac.et.ms = 10;
  } else if (strncmp(cmd, "100_ms", max_str_sz) == 0 ) {
    mac.et.ms = 100;
  } else {"""
    if text.count(old) != 1 or 'strncmp(cmd, "100_ms"' in text:
        raise RuntimeError("Unexpected MAC interval parser anchor")
    return text.replace(old, new, 1)

def transform_xapp(text):
    old = '(void*)"10_ms"'
    if text.count(old) != 2:
        raise RuntimeError("Expected two 10 ms MAC subscriptions")
    return text.replace(old, '(void*)"100_ms"')

if __name__ == "__main__":
    sdk = Path("/src/flexric/src/sm/mac_sm/mac_sm_ric.c")
    xapp = Path("/src/test/xapp/xapp_oai_mac_counters.c")
    updated_sdk = transform_sdk(sdk.read_text())
    updated_xapp = transform_xapp(xapp.read_text())
    sdk.write_text(updated_sdk)
    xapp.write_text(updated_xapp)
    print("Applied: dedicated 100 ms MAC collection")
