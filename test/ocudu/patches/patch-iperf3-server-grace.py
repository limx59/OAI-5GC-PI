#!/usr/bin/env python3
"""Allow a bounded laboratory override of iperf3 server completion grace."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    root = args.source_root.resolve()
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise RuntimeError("Apply only to an extracted Docker build source")
    path = root / "src/iperf_server_api.c"
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise RuntimeError("Missing or unexpected iperf3 source")
    text = path.read_text()
    old = "    int grace_period = max_rtt * state_transitions;"
    new = old + r"""
    const char *lab_grace = getenv("LAB_IPERF_SERVER_GRACE_SECONDS");
    if (lab_grace != NULL) {
        char *end = NULL;
        long seconds = strtol(lab_grace, &end, 10);
        if (end == lab_grace || *end != '\0' ||
            seconds < 40 || seconds > 600) {
            fprintf(stderr, "Invalid LAB_IPERF_SERVER_GRACE_SECONDS\n");
            return -1;
        }
        grace_period = (int) seconds;
        fprintf(stderr, "LAB_IPERF_SERVER_GRACE seconds=%d\n", grace_period);
    }"""
    if text.count(old) != 1:
        raise RuntimeError("Unexpected server grace anchor")
    text = text.replace(old, new, 1)
    text = "#include <stdlib.h>\n#include <stdio.h>\n" + text
    path.write_text(text)
    print("PATCHED: bounded server grace override; default remains 40 seconds")


if __name__ == "__main__":
    main()
