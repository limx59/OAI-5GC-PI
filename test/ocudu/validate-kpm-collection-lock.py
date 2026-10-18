#!/usr/bin/env python3
"""Run isolated KPM collection-lock unit tests using the published ARM64 image."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

IMAGE = "limx59/oai-pi-ocudu-kpm-tests:arm64-collection-lock"
DIGEST = "sha256:3e9c2865bc29f4161ab56ae7dd823e33f98c637ee4fbb94840bcd2027df6e855"
FILTER = (
    "e2sm_kpm_collection_lock.*:"
    "e2sm_kpm_style4_record_guard.*:"
    "e2sm_kpm_report_service_style2_test.*:"
    "*e2sm_kpm_generates_ric_indication_style4*"
)
DOCKER = ["sudo", "docker"]


def text_output(value):
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path.home() / "Work/oai-test-evidence",
    )
    args = parser.parse_args()
    parent = args.output_dir.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="ocudu-kpm-lock-dockerhub-", dir=parent))
    name = "ocudu-kpm-lock-unit-" + uuid.uuid4().hex[:12]
    summary = {
        "scope": "KPM collection-lock unit regression; not one-second timing acceptance",
        "image": IMAGE,
        "expected_digest": DIGEST,
        "passed": False,
        "cleanup_errors": [],
    }
    print(f"Evidence: {evidence}", flush=True)
    container_attempted = False
    try:
        result = subprocess.run(
            DOCKER + ["image", "inspect", IMAGE],
            capture_output=True, text=True, check=True, timeout=30,
        )
        image = json.loads(result.stdout)[0]
        metadata = {
            "id": image["Id"],
            "repo_digests": image.get("RepoDigests", []),
            "architecture": image["Architecture"],
            "os": image["Os"],
        }
        (evidence / "image.json").write_text(json.dumps(metadata, indent=2) + "\n")
        expected = IMAGE.split(":")[0] + "@" + DIGEST
        if expected not in metadata["repo_digests"]:
            raise RuntimeError("Published image digest mismatch; pull the documented image first")
        if metadata["architecture"] != "arm64" or metadata["os"] != "linux":
            raise RuntimeError("Expected a Linux ARM64 image")

        command = DOCKER + [
            "run", "--name", name, "--pull", "never",
            "--network", "none", "--cpus", "1", "--memory", "1g",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={evidence},dst=/evidence",
            IMAGE, "/build/ocudu/tests/unittests/e2/e2sm_kpm_test",
            f"--gtest_filter={FILTER}",
            "--gtest_output=xml:/evidence/results.xml",
        ]
        (evidence / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        container_attempted = True
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=240,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as error:
            (evidence / "stdout.log").write_text(text_output(error.stdout))
            (evidence / "stderr.log").write_text(text_output(error.stderr))
            raise RuntimeError("Unit-test container exceeded 240 seconds") from error

        (evidence / "stdout.log").write_text(result.stdout)
        (evidence / "stderr.log").write_text(result.stderr)
        summary["exit_code"] = result.returncode
        print("\n".join(result.stdout.splitlines()[-12:]), flush=True)
        if result.returncode:
            raise RuntimeError("Unit-test container failed; inspect retained logs")

        document = ET.parse(evidence / "results.xml").getroot()
        cases = document.findall(".//testcase")
        summary["xml_totals"] = document.attrib
        if len(cases) != 7 or int(document.get("tests", "0")) != 7:
            raise RuntimeError("Expected exactly seven test cases")
        if any(int(document.get(key, "0")) for key in ("failures", "errors", "disabled")):
            raise RuntimeError("XML reports failed, errored or disabled tests")
        if any(
            case.get("status") != "run"
            or case.get("result") not in (None, "completed")
            or any(case.find(key) is not None for key in ("failure", "error", "skipped"))
            for case in cases
        ):
            raise RuntimeError("A test case did not complete successfully")
        summary["passed"] = True
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
    finally:
        if container_attempted:
            try:
                result = subprocess.run(
                    DOCKER + ["rm", "-f", name],
                    capture_output=True, text=True, timeout=30,
                )
                (evidence / "cleanup.log").write_text(result.stdout + result.stderr)
                if result.returncode:
                    summary["cleanup_errors"].append(result.stderr.strip())
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if summary["cleanup_errors"]:
            summary["passed"] = False
        summary["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Evidence retained: {evidence}", flush=True)

    if not summary["passed"]:
        raise SystemExit("FAIL: " + summary.get("error", "container cleanup failed"))
    print("PASS: seven published-image unit tests; temporary container removed.")
    print("One-second monitoring acceptance remains pending.")


if __name__ == "__main__":
    main()
