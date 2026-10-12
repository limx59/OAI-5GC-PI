#!/usr/bin/env python3
"""Prepare only the Docker copy of the OAI SDK for the context query."""
from pathlib import Path

sdk = Path("/src/flexric")
if not sdk.is_dir():
    raise SystemExit("Only the Docker SDK copy /src/flexric is supported.")

(sdk / "examples/CMakeLists.txt").write_text(
    """add_subdirectory(xApp/c/monitor/RRC_MESSAGES)
add_executable(xapp_oai_ue_context
    /src/test/xapp/xapp_oai_ue_context.c
    ${CMAKE_SOURCE_DIR}/src/util/alg_ds/alg/defer.c)
target_link_libraries(xapp_oai_ue_context PRIVATE
    e42_xapp -pthread -lsctp -ldl)
""", encoding="utf-8")
print("Prepared dedicated query target in Docker SDK copy.")
