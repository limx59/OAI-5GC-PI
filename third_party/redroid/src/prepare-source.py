#!/usr/bin/env python3
"""Overlay vendored ReDroid sources or apply Android 12 patches."""

import argparse
import shutil
import subprocess
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent
AOSP_TAG = "android-12.0.0_r34"
OVERLAYS = {
    "device_redroid": "device/redroid",
    "redroid-c2": "hardware/redroid/c2",
    "redroid-omx": "hardware/redroid/omx",
    "vendor_redroid": "vendor/redroid",
    "chromium-webview-stub": "external/chromium-webview",
}


def overlay(aosp):
    for name in OVERLAYS:
        if not (SOURCE_ROOT / name).is_dir():
            raise SystemExit(f"Missing vendored source: {name}")

    for name, destination in OVERLAYS.items():
        target = aosp / destination
        # Merge without deleting WebView prebuilt directories fetched by repo.
        shutil.copytree(
            SOURCE_ROOT / name,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git"),
        )
        print(f"Copied {name} -> {target}")


def apply_patches(aosp):
    patch_root = SOURCE_ROOT / "redroid-patches" / AOSP_TAG
    groups = {}
    for patch in sorted(patch_root.rglob("*.patch")):
        project = patch.parent.relative_to(patch_root)
        groups.setdefault(project, []).append(patch)

    if not groups:
        raise SystemExit(f"No patches found for {AOSP_TAG}")

    # Check all target repositories before applying any patches.
    for project in groups:
        target = aosp / project
        if not target.is_dir():
            raise SystemExit(f"Missing AOSP project: {project}")
        status = subprocess.check_output(
            ["git", "-C", str(target), "status", "--porcelain"],
            text=True,
        )
        if status.strip():
            raise SystemExit(f"AOSP project is not clean: {project}")
        state = subprocess.check_output(
            ["git", "-C", str(target), "rev-parse", "--git-path", "rebase-apply"],
            text=True,
        ).strip()
        state_path = Path(state)
        if not state_path.is_absolute():
            state_path = target / state_path
        if state_path.exists():
            raise SystemExit(f"An unfinished git am operation exists: {project}")

    for project, patches in groups.items():
        print(f"Applying patches: {project}", flush=True)
        subprocess.run(
            ["git", "-C", str(aosp / project), "am",
             *map(str, patches)],
            check=True,
        )
    print("All ReDroid patches were applied successfully.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("overlay", "patch"))
    parser.add_argument("aosp", type=Path)
    arguments = parser.parse_args()
    aosp = arguments.aosp.expanduser().resolve()
    if not (aosp / "build/envsetup.sh").is_file():
        raise SystemExit("Synchronize the Android AOSP source tree first.")
    if arguments.action == "overlay":
        overlay(aosp)
    else:
        apply_patches(aosp)


if __name__ == "__main__":
    main()
