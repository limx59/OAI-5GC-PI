#!/usr/bin/env python3
"""Build and test the RLC counter patch in a disposable build environment."""

from datetime import datetime, timezone
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
DOCKER = ["sudo", "docker"]

PROGRAM = """
from pathlib import Path
import subprocess
import sys

subprocess.run([
    sys.executable, "-B", "/evidence/patch-ocudu-rlc-report-counter.py",
    "/src/ocudu",
], check=True)
path = Path("/src/ocudu/tests/unittests/rlc/rlc_bearer_metrics_collector_test.cpp")
path.write_text(path.read_text() + "\\n" +
                Path("/evidence/rlc-report-counter-tests.inc").read_text())
subprocess.run([
    "cmake", "--build", "/build/ocudu",
    "--target", "rlc_bearer_metrics_collector_test", "--parallel", "1",
], check=True, timeout=1800)
subprocess.run([
    "timeout", "--signal=TERM", "--kill-after=5s", "180s",
    "/build/ocudu/tests/unittests/rlc/rlc_bearer_metrics_collector_test",
    "--gtest_output=xml:/evidence/results.xml",
], check=True, timeout=200)
"""


def command(args, **kwargs):
    return subprocess.run(
        DOCKER + args, stdin=subprocess.DEVNULL,
        timeout=kwargs.pop("timeout", 30), **kwargs,
    )


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-rlc-counter-", dir=parent))
    print(f"Evidence: {dest}", flush=True)
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "cleanup_errors": [],
        "scope": "RLC collector counter regression; not one-second monitoring acceptance",
    }
    name = "ocudu-rlc-counter-" + uuid.uuid4().hex[:16]
    created = False
    try:
        for filename in (
            "patch-ocudu-rlc-report-counter.py",
            "rlc-report-counter-tests.inc",
        ):
            shutil.copyfile(root / "test/ocudu/patches" / filename, dest / filename)
        (dest / "runner.py").write_text(PROGRAM)

        inspected = command(
            ["image", "inspect", "--format",
             '{"id":{{json .Id}},"architecture":{{json .Architecture}},"os":{{json .Os}}}',
             IMAGE], capture_output=True, text=True, check=True,
        )
        metadata = json.loads(inspected.stdout)
        summary["build_environment"] = metadata
        if metadata["architecture"] != "arm64" or metadata["os"] != "linux":
            raise RuntimeError("Expected Linux ARM64 build environment")

        command([
            "create", "--name", name, "--pull", "never",
            "--network", "none", "--cpus", "1",
            "--mount", f"type=bind,src={dest},dst=/evidence",
            "--entrypoint", "python3", metadata["id"],
            "-u", "/evidence/runner.py",
        ], capture_output=True, text=True, check=True)
        created = True

        with (dest / "build-and-test.log").open("w") as log:
            result = command(
                ["start", "--attach", name], stdout=log,
                stderr=subprocess.STDOUT, timeout=2100,
            )
        summary["returncode"] = result.returncode
        if result.returncode:
            raise RuntimeError("Build or test failed; inspect build-and-test.log")

        xml = ET.parse(dest / "results.xml").getroot()
        cases = xml.findall(".//testcase")
        if len(cases) != 3 or int(xml.get("tests", "-1")) != 3:
            raise RuntimeError("Expected exactly three tests")
        if any(int(xml.get(key, "0")) for key in ("failures", "errors", "disabled")):
            raise RuntimeError("Test failures, errors or disabled tests")
        for case in cases:
            if (case.get("status") != "run"
                    or case.get("result") not in (None, "completed")
                    or any(case.find(tag) is not None
                           for tag in ("failure", "error", "skipped"))):
                raise RuntimeError("Unsuccessful test case")
        if "preserves_matched_counter_including_wraparound" not in {
            case.get("name") for case in cases
        }:
            raise RuntimeError("New counter regression missing")
        summary["tests"] = len(cases)
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
    finally:
        if created:
            try:
                result = command(["rm", "--force", name], capture_output=True, text=True)
                (dest / "cleanup.log").write_text(result.stdout + result.stderr)
                if result.returncode:
                    summary["cleanup_errors"].append(result.stderr.strip())
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if summary["cleanup_errors"]:
            summary["passed"] = False
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Evidence retained: {dest}", flush=True)

    if not summary["passed"]:
        raise SystemExit("FAIL: inspect summary.json and build-and-test.log")
    print("PASS: three RLC counter tests; temporary build container removed.")
    print("No deployment image or service changes; one-second acceptance pending.")


if __name__ == "__main__":
    main()
