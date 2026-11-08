#!/usr/bin/env python3
"""Trace the API root selected for nudr-dr in a disposable Open5GS build."""
import argparse
from pathlib import Path


ORIGINAL = '''            ogs_debug("apiroot [%s]", apiroot);
            ogs_sbi_header_set(request->http.headers,
                    OGS_SBI_CUSTOM_TARGET_APIROOT, apiroot);
'''

TRACED = '''            ogs_debug("apiroot [%s]", apiroot);
            if (strcmp(request->h.service.name, "nudr-dr") == 0)
                ogs_info("NUDR target-apiroot trace [%s]", apiroot);
            ogs_sbi_header_set(request->http.headers,
                    OGS_SBI_CUSTOM_TARGET_APIROOT, apiroot);
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = args.source_root.resolve()
    source = root / "lib/sbi/path.c"
    if args.apply and (
        root != Path("/open5gs") or not Path("/.dockerenv").is_file()
    ):
        parser.error("--apply requires the disposable /open5gs Docker build copy")
    try:
        source.resolve().relative_to(root)
    except ValueError:
        parser.error("source path escapes the Open5GS source root")

    original = source.read_bytes()
    anchor = ORIGINAL.encode()
    if original.count(anchor) != 1:
        raise SystemExit("STOP: expected exactly one target-apiroot source anchor")

    if args.apply:
        source.write_bytes(original.replace(anchor, TRACED.encode(), 1))
        print("PASS: added nudr-dr API-root trace to the Docker build copy")
    else:
        print("PASS: target-apiroot anchor matched; source was only read")


if __name__ == "__main__":
    main()
