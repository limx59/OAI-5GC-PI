#!/usr/bin/env python3
"""Prepare matching OAI KPM plugins for the local E2 interoperability test."""

import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def prepare(build):
    cache = build / "CMakeCache.txt"
    settings = {}
    for line in cache.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "//")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.split(":", 1)[0]] = value

    expected = {
        "E2_AGENT": "ON",
        "E2AP_VERSION": "E2AP_V2",
        "KPM_VERSION": "KPM_V3_00",
    }
    for key, value in expected.items():
        if settings.get(key) != value:
            raise ValueError(f"Expected {key}={value}; found {settings.get(key)!r}.")

    if not (build / "nr-softmodem").is_file():
        raise ValueError("Build nr-softmodem first.")

    models = build / "openair2/E2AP/flexric/src/sm"
    matches = list(models.rglob("libkpm_sm.so"))
    if len(matches) != 1:
        raise ValueError(f"Expected one built KPM plugin; found {len(matches)}.")

    destination = build / "e2-sm-plugins-kpm"
    if destination.exists():
        extras = [p.name for p in destination.iterdir()
                  if p.name != "libkpm_sm.so"]
        if extras:
            raise ValueError(f"KPM-only directory contains unexpected entries: {extras}")

    destination.mkdir(exist_ok=True)
    shutil.copy2(matches[0], destination / "libkpm_sm.so")
    print(f"Prepared KPM-only plugins: {destination}")
    print(f"Launch nr-softmodem with working directory: {build}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-dir", type=Path,
        default=PROJECT_ROOT / "oai/cmake_targets/ran_build/build",
    )
    args = parser.parse_args()
    try:
        prepare(args.build_dir.resolve())
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
