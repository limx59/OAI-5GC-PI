#!/usr/bin/env python3
"""Add MAC collector only to the Docker copy of the matched OAI SDK."""
from pathlib import Path
sdk = Path("/src/flexric")
p = sdk / "examples/CMakeLists.txt"
if not sdk.is_dir() or not p.is_file():
    raise SystemExit("Prepared Docker SDK /src/flexric is required.")
text = p.read_text(encoding="utf-8")
if "xapp_oai_mac_counters" in text:
    raise SystemExit("MAC target already exists.")
p.write_text(text + """
add_executable(xapp_oai_mac_counters
    /src/test/xapp/xapp_oai_mac_counters.c
    ${CMAKE_SOURCE_DIR}/src/util/alg_ds/alg/defer.c)
target_link_libraries(xapp_oai_mac_counters PRIVATE
    e42_xapp -pthread -lsctp -ldl)
""", encoding="utf-8")
print("Added MAC collector target to Docker SDK copy.")
