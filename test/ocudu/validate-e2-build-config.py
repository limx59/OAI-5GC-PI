#!/usr/bin/env python3
"""Validate OCUDU E2 build configuration in an existing builder image."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile

CHECK = r"""
from pathlib import Path
import json
import re
import subprocess

build = Path("/build/ocudu")
cache_path = build / "CMakeCache.txt"
values = {}
for line in cache_path.read_text().splitlines():
    match = re.match(r"([^/#][^:]*):[^=]+=(.*)$", line)
    if match:
        values[match.group(1)] = match.group(2)

expected = {
    "CMAKE_BUILD_TYPE": "Release",
    "BUILD_TESTING": "ON",
    "ENABLE_ZEROMQ": "ON",
    "ENABLE_EXPORT": "ON",
    "ENABLE_PLUGINS": "OFF",
    "MCPU": "cortex-a76+crypto",
    "MARCH": "armv8.2-a",
    "CMAKE_HOME_DIRECTORY": "/src/ocudu",
}
mismatches = {
    key: {"expected": wanted, "actual": values.get(key)}
    for key, wanted in expected.items()
    if values.get(key) != wanted
}

result = subprocess.run(
    ["ninja", "-C", str(build), "-t", "commands", "gnb_split_8"],
    capture_output=True, text=True, check=True,
)
links = [
    line for line in result.stdout.splitlines()
    if re.search(r"-o\s+\S*/gnb\s", line)
]
libraries = ("libocudu_e2.a", "libe2ap_asn1.a")
linked = any(all(name in line for name in libraries) for line in links)
passed = not mismatches and linked
print(json.dumps({
    "passed": passed,
    "cache": {key: values.get(key) for key in expected},
    "mismatches": mismatches,
    "e2_libraries_in_gnb_link_command": linked,
    "gnb_link_commands": links,
}, indent=2))
raise SystemExit(0 if passed else 1)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default="limx59/oai-pi-ocudu-kpm-tests:arm64-clock-selection",
    )
    parser.add_argument(
        "--output-root", type=Path,
        default=Path.home() / "Work/oai-test-evidence",
    )
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix="ocudu-e2-build-config-", dir=args.output_root,
    ))
    summary = {
        "passed": False,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "image": args.image,
        "scope": "Builder cache and configured gNB E2 link dependencies",
        "limitations": (
            "Does not compile, inspect the final runtime binary, or run "
            "E2 traffic; integration validation is performed separately."
        ),
    }
    try:
        inspected = subprocess.run(
            ["sudo", "docker", "image", "inspect", args.image],
            capture_output=True, text=True, timeout=30,
        )
        if inspected.returncode:
            raise RuntimeError(inspected.stderr.strip())
        info = json.loads(inspected.stdout)[0]
        summary["image_id"] = info["Id"]
        summary["architecture"] = info.get("Architecture")
        summary["repo_digests"] = info.get("RepoDigests", [])
        if summary["architecture"] != "arm64":
            raise RuntimeError("Expected an ARM64 builder image")

        result = subprocess.run([
            "sudo", "docker", "run", "--rm", "--pull", "never",
            "--network", "none", "--entrypoint", "python3",
            args.image, "-c", CHECK,
        ], capture_output=True, text=True, timeout=120)
        (dest / "check.stdout").write_text(result.stdout)
        (dest / "check.stderr").write_text(result.stderr)
        summary["check_exit"] = result.returncode
        try:
            summary["check"] = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("Build check did not return valid JSON")
        summary["passed"] = (
            result.returncode == 0
            and summary["check"].get("passed") is True
        )
    except Exception as error:
        summary["error"] = str(error)
    finally:
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        print(f"Evidence: {dest}", flush=True)
        display = dict(summary)
        if "check" in display:
            display["check"] = {
                key: value for key, value in display["check"].items()
                if key != "gnb_link_commands"
            }
        print(json.dumps(display, indent=2), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
