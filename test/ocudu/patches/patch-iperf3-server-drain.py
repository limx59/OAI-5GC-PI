#!/usr/bin/env python3
"""Add an opt-in bounded UDP receive drain before final server statistics."""
import argparse
from pathlib import Path
import subprocess
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected source anchor: " + old[:100])
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    root = args.source_root.resolve()
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise RuntimeError("Apply only to an extracted Docker build source")

    server = root / "src/iperf_server_api.c"
    udp = root / "src/iperf_udp.c"
    for path in (server, udp):
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise RuntimeError("Missing or unexpected source")

    anchor = "        case TEST_END:\n"
    drain = r"""
            if (test->protocol->id == Pudp && test->mode == RECEIVER) {
                const char *enabled = getenv("LAB_IPERF_UDP_DRAIN");
                if (enabled != NULL && strcmp(enabled, "1") == 0) {
                    unsigned ticks = 0, quiet = 0;
                    unsigned long long initial = test->bytes_received;
                    unsigned long long previous = initial;
                    const struct timespec delay = {0, 10000000L};
                    while (ticks < 500 && quiet < 50) {
                        unsigned long long current;
                        if (nanosleep(&delay, NULL) != 0)
                            break;
                        ++ticks;
                        current = test->bytes_received;
                        if (current == previous)
                            ++quiet;
                        else
                            quiet = 0;
                        previous = current;
                    }
                    fprintf(stderr,
                            "LAB_IPERF_UDP_DRAIN before=%llu after=%llu "
                            "polls=%u quiet_reached=%d\n",
                            initial, previous, ticks, quiet >= 50);
                }
            }
"""
    server_text = once(server.read_text(), anchor, anchor + drain)
    udp_old = "    if (sp->test->state == TEST_RUNNING) {"
    udp_new = r"""    if (sp->test->state == TEST_RUNNING ||
        (sp->test->state == TEST_END &&
         getenv("LAB_IPERF_UDP_DRAIN") != NULL &&
         strcmp(getenv("LAB_IPERF_UDP_DRAIN"), "1") == 0)) {"""
    udp_text = once(udp.read_text(), udp_old, udp_new)

    base = Path(__file__).with_name("patch-iperf3-server-grace.py")
    if not base.is_file():
        raise RuntimeError("Missing prerequisite grace patch")
    subprocess.run(
        [sys.executable, "-B", str(base), str(root)], check=True,
    )

    # Retain the prerequisite patch while adding the checked drain block.
    server_text = once(server.read_text(), anchor, anchor + drain)
    server.write_text(
        "#include <time.h>\n#include <string.h>\n" + server_text
    )
    udp.write_text(
        "#include <stdlib.h>\n#include <string.h>\n" + udp_text
    )
    print("PATCHED: opt-in TEST_END UDP accounting and bounded receive drain")


if __name__ == "__main__":
    main()
