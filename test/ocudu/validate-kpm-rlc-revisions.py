#!/usr/bin/env python3
"""Compile RLC revision tracking and run existing metric regressions."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

IMAGE = (
    "limx59/oai-pi-ocudu-kpm-tests@"
    "sha256:2f31c97bfc5a9cb6b4bbc0ef9020f6a9c6d780cc34bb086b5781764ee7dead48"
)
PROGRAM = """
from pathlib import Path
import subprocess
import sys
subprocess.run([
    sys.executable, "-B", "/evidence/patch-ocudu-kpm-rlc-revisions.py",
    "/src/ocudu",
], check=True)
test_source = Path("/src/ocudu/tests/unittests/e2/e2sm_kpm_meas_provider_metrics_test.cpp")
test_source.write_text(test_source.read_text() + "\\n" +
                       Path("/evidence/kpm-rlc-revisions-tests.inc").read_text())
subprocess.run([
    "cmake", "--build", "/build/ocudu",
    "--target", "e2sm_kpm_meas_provider_metrics_test", "--parallel", "1",
], check=True, timeout=1800)
subprocess.run([
    "timeout", "--signal=TERM", "--kill-after=5s", "180s",
    "/build/ocudu/tests/unittests/e2/e2sm_kpm_meas_provider_metrics_test",
    "--gtest_output=xml:/evidence/results.xml",
], check=True, timeout=200)
"""


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-rlc-revisions-", dir=parent))
    shutil.copyfile(
        root / "test/ocudu/patches/patch-ocudu-kpm-rlc-revisions.py",
        dest / "patch-ocudu-kpm-rlc-revisions.py",
    )
    shutil.copyfile(
        root / "test/ocudu/patches/kpm-rlc-revisions-tests.inc",
        dest / "kpm-rlc-revisions-tests.inc",
    )
    (dest / "runner.py").write_text(PROGRAM)
    name = "ocudu-rlc-revisions-" + uuid.uuid4().hex[:12]
    docker = ["sudo", "docker"]
    summary = {
        "passed": False,
        "scope": "RLC revision tracking and metric regressions; subscription freshness not validated",
        "cleanup_errors": [],
    }
    print(f"Evidence: {dest}", flush=True)
    try:
        inspected = subprocess.run(
            docker + ["image", "inspect", IMAGE],
            check=True, capture_output=True, text=True, timeout=30,
        )
        info = json.loads(inspected.stdout)[0]
        if info["Architecture"] != "arm64" or info["Os"] != "linux":
            raise RuntimeError("Expected Linux ARM64 build environment")
        summary["build_environment"] = info["Id"]
        subprocess.run(
            docker + [
                "create", "--name", name, "--pull", "never",
                "--network", "none", "--cpus", "1",
                "--mount", f"type=bind,src={dest},dst=/evidence",
                "--entrypoint", "python3", info["Id"],
                "-u", "/evidence/runner.py",
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
        with (dest / "build-test.log").open("w") as log:
            result = subprocess.run(
                docker + ["start", "--attach", name],
                stdout=log, stderr=subprocess.STDOUT, timeout=2100,
            )
        summary["returncode"] = result.returncode
        if result.returncode:
            raise RuntimeError("Build or tests failed; inspect build-test.log")
        report = ET.parse(dest / "results.xml").getroot()
        cases = report.findall(".//testcase")
        if not cases or any(
            case.find("failure") is not None
            or case.find("error") is not None
            or case.find("skipped") is not None
            or case.get("status") != "run"
            for case in cases
        ):
            raise RuntimeError("Missing, failed or skipped tests")
        required = {
            "rlc_revision_tracks_source_counter_without_consuming",
            "rlc_revisions_are_separate_for_ues_and_bearers",
            "mismatched_rlc_component_counters_do_not_advance_revision",
        }
        if len(cases) != 16 or not required.issubset(
            {case.get("name") for case in cases}
        ):
            raise RuntimeError("Expected 13 existing and three revision tests")
        summary["tests"] = len(cases)
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
    finally:
        cleanup = subprocess.run(
            docker + ["rm", "--force", name],
            capture_output=True, text=True, timeout=30,
        )
        (dest / "cleanup.log").write_text(cleanup.stdout + cleanup.stderr)
        if cleanup.returncode:
            summary["cleanup_errors"].append(cleanup.stderr.strip())
            summary["passed"] = False
        (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"Evidence retained: {dest}")
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
