# FlexRIC subscription failure source snapshots

- `original/`: source files before applying the listed patches.
- `patched/`: source files after applying all six patches.
- `changes.patch`: combined unified source diff.
- `manifest.json`: patch order and SHA-256 checksums.

These snapshots are review material. Docker builds continue to use the Python patch scripts in the parent directory.

Only patch application has been checked. Compilation and behavior tests remain pending. Regenerate snapshots after changing patches.
