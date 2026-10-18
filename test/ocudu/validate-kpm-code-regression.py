#!/usr/bin/env python3
"""Run isolated KPM unit regressions and retain machine-readable evidence."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

DOCKER = ["sudo", "docker"]
LOCK_IMAGE = (
    "limx59/oai-pi-ocudu-kpm-tests@"
    "sha256:3e9c2865bc29f4161ab56ae7dd823e33f98c637ee4fbb94840bcd2027df6e855"
)
CLOCK_IMAGE = "limx59/oai-pi-ocudu-kpm-tests:arm64-clock-selection"
LOCK_FILTER = (
    "e2sm_kpm_collection_lock.*:"
    "e2sm_kpm_style4_record_guard.*:"
    "e2sm_kpm_report_service_style2_test.*:"
    "*e2sm_kpm_generates_ric_indication_style4*"
)


def docker(args, timeout=30):
    return subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )


def checked(args):
    result = docker(args)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clock-image", default=CLOCK_IMAGE)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path.home() / "Work/oai-test-evidence",
    )
    args = parser.parse_args()
    parent = args.output_dir.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-kpm-code-regression-", dir=parent))
    print(f"Evidence: {dest}", flush=True)

    cases = [
        ("collection-lock", LOCK_IMAGE, "e2sm_kpm_test", LOCK_FILTER),
        ("subscription-clock", args.clock_image, "e2_subscription_setup_test", "*"),
    ]
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": "KPM unit regressions; one-second monitoring acceptance excluded",
        "passed": False, "runs": [], "cleanup_errors": [],
    }

    try:
        for label, reference, binary, test_filter in cases:
            directory = dest / label
            directory.mkdir()
            metadata = json.loads(checked([
                "image", "inspect", "--format",
                '{"id":{{json .Id}},"architecture":{{json .Architecture}},'
                '"os":{{json .Os}},"repo_digests":{{json .RepoDigests}}}',
                reference,
            ]))
            (directory / "image.json").write_text(json.dumps(metadata, indent=2) + "\n")
            if metadata["architecture"] != "arm64" or metadata["os"] != "linux":
                raise RuntimeError(f"{label}: expected Linux ARM64 image")

            # Run by immutable local image ID, even when the input is a tag.
            name = "ocudu-kpm-unit-" + uuid.uuid4().hex[:16]
            record = {"label": label, "image": reference, "image_id": metadata["id"],
                      "passed": False}
            summary["runs"].append(record)
            created = False
            try:
                checked([
                    "create", "--name", name, "--pull", "never",
                    "--network", "none", "--cpus", "1",
                    "--user", f"{os.getuid()}:{os.getgid()}",
                    "--mount", f"type=bind,src={directory},dst=/evidence",
                    metadata["id"],
                    "timeout", "--signal=TERM", "--kill-after=5s", "180s",
                    f"/build/ocudu/tests/unittests/e2/{binary}",
                    f"--gtest_filter={test_filter}",
                    "--gtest_output=xml:/evidence/results.xml",
                ])
                created = True
                result = docker(["start", "--attach", name], timeout=210)
                (directory / "stdout.log").write_text(result.stdout)
                (directory / "stderr.log").write_text(result.stderr)
                record["returncode"] = result.returncode
                if result.returncode:
                    raise RuntimeError(f"{label}: test process returned {result.returncode}")

                xml = ET.parse(directory / "results.xml").getroot()
                tests = xml.findall(".//testcase")
                if len(tests) != 7 or int(xml.get("tests", "-1")) != 7:
                    raise RuntimeError(f"{label}: expected exactly seven tests")
                for attribute in ("failures", "errors", "disabled"):
                    if int(xml.get(attribute, "0")):
                        raise RuntimeError(f"{label}: nonzero {attribute}")
                for test in tests:
                    if (test.get("status") != "run"
                            or test.get("result") not in (None, "completed")
                            or any(test.find(tag) is not None
                                   for tag in ("failure", "error", "skipped"))):
                        raise RuntimeError(f"{label}: unsuccessful test {test.get('name')}")
                if label == "subscription-clock":
                    required = {
                        "kpm_report_uses_independent_timer",
                        "deletion_does_not_collect_or_send",
                        "header_preserves_current_window_before_message_reset",
                    }
                    if not required.issubset({test.get("name") for test in tests}):
                        raise RuntimeError("Required clock/lifecycle tests missing")

                record["tests"] = len(tests)
                record["passed"] = True
                print(f"PASS: {label}: seven tests", flush=True)
            finally:
                if created:
                    try:
                        cleanup = docker(["rm", "--force", name])
                        (directory / "cleanup.log").write_text(
                            cleanup.stdout + cleanup.stderr)
                        if cleanup.returncode:
                            summary["cleanup_errors"].append(f"{label}: {cleanup.stderr.strip()}")
                    except Exception as error:
                        summary["cleanup_errors"].append(f"{label}: {error}")

        summary["passed"] = (
            len(summary["runs"]) == 2
            and all(run["passed"] for run in summary["runs"])
            and not summary["cleanup_errors"]
        )
    except Exception as error:
        summary["error"] = str(error)
    finally:
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Evidence retained: {dest}", flush=True)

    if not summary["passed"]:
        raise SystemExit("FAIL: inspect summary.json and per-suite logs.")
    print("PASS: 14 unit tests; temporary containers removed.")
    print("One-second monitoring acceptance remains pending.")


if __name__ == "__main__":
    main()
