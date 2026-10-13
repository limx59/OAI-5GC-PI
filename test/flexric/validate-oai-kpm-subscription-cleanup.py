#!/usr/bin/env python3
"""Run repeated OAI KPM recording and subscription cleanup checks."""

import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xapp-image",
        default="limx59/flexric-xapp:arm64-subscription-cleanup",
    )
    parser.add_argument(
        "--pull-policy", choices=("always", "never"), default="always",
    )
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/oai-kpm-subscription-cleanup"),
    )
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")

    validator = Path(__file__).resolve().with_name(
        "validate-oai-kpm-recording.py"
    )
    if not validator.is_file():
        parser.error(f"Recording validator not found: {validator}")

    repo = validator.parents[2]
    output = args.output_dir.resolve()

    for number in range(1, args.rounds + 1):
        print(
            f"\n=== KPM regression round {number}/{args.rounds} ===",
            flush=True,
        )
        pull_policy = args.pull_policy if number == 1 else "never"
        try:
            subprocess.run([
                sys.executable, str(validator),
                "--xapp-image", args.xapp_image,
                "--pull-policy", pull_policy,
                "--output-dir", str(output),
            ], cwd=repo, check=True)
        except subprocess.CalledProcessError as exc:
            print(
                f"FAIL: regression stopped at round {number}/{args.rounds}.",
                file=sys.stderr,
                flush=True,
            )
            return exc.returncode if exc.returncode > 0 else 1

    print(
        f"\nPASS: all {args.rounds} uplink/downlink regression rounds completed.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
