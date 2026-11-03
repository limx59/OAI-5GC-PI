#!/usr/bin/env python3
"""Validate existing offline OCUDU slice scheduler tests."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "limx59/oai-pi-ocudu-scheduler-tests:arm64-slicing-test@sha256:a6432f1ea245d94dc8f14b8325034feef36bef66ab142413d6489525f6b0b4cb"
BINARY = "/build/ocudu/tests/unittests/scheduler/slicing/slice_scheduler_test"
DOCKER = ["sudo", "docker"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def progress(message):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
          + " " + message, flush=True)


def docker(args, timeout=30):
    return subprocess.check_output(
        DOCKER + args, text=True, stderr=subprocess.PIPE, timeout=timeout,
    ).strip()


def main():
    parent = ROOT / "test/ocudu/.local/evidence"
    require(parent.resolve().is_relative_to(ROOT),
            "Evidence directory outside repository")
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-slice-scheduler-", dir=parent))
    dest.chmod(0o700)
    name = "ocudu-slice-test-" + uuid.uuid4().hex[:12]
    created = False
    summary = {
        "passed": False,
        "scope": "Existing offline OCUDU slice scheduler tests only",
        "network": "none",
        "control_requests_sent": 0,
        "cleanup_errors": [],
    }
    progress("Evidence: " + str(dest))
    try:
        progress("Checking local test image")
        image = json.loads(docker(["image", "inspect", IMAGE]))[0]
        require(image["Os"] == "linux"
                and image["Architecture"] == "arm64",
                "Expected linux/arm64 image")
        summary["image"] = {
            "reference": IMAGE, "id": image["Id"],
            "os": image["Os"], "architecture": image["Architecture"],
        }

        cid = docker([
            "create", "--pull=never", "--name", name,
            "--network=none", "--ulimit", "core=0:0",
            "--entrypoint", "timeout", image["Id"],
            "--signal=TERM", "--kill-after=5s", "180s",
            BINARY, "--gtest_color=no",
            "--gtest_output=xml:/tmp/slice-scheduler.xml",
        ])
        created = True
        summary["container_id"] = cid
        progress("Running slice_scheduler_test; limit 180 seconds")
        with (dest / "test.log").open("w") as stream:
            result = subprocess.run(
                DOCKER + ["start", "--attach", cid],
                stdout=stream, stderr=subprocess.STDOUT,
                text=True, timeout=210,
            )
        summary["docker_attach_returncode"] = result.returncode

        state = json.loads(docker(["inspect", cid]))[0]["State"]
        summary["container_state"] = {
            key: state.get(key) for key in
            ("Running", "ExitCode", "OOMKilled", "Error")
        }
        progress("Collecting GoogleTest XML")
        docker(["cp", cid + ":/tmp/slice-scheduler.xml",
                str(dest / "results.xml")])

        require(result.returncode == 0, "Docker attached run failed")
        require(not state["Running"] and state["ExitCode"] == 0
                and not state["OOMKilled"] and not state.get("Error"),
                "Test container failed or was OOM-killed")

        report = ET.parse(dest / "results.xml").getroot()
        cases = list(report.iter("testcase"))
        require(cases, "GoogleTest report contains no tests")
        require(int(report.attrib.get("tests", "-1")) == len(cases),
                "GoogleTest test count mismatch")
        require(int(report.attrib.get("failures", "-1")) == 0,
                "GoogleTest reported failures")
        require(int(report.attrib.get("errors", "-1")) == 0,
                "GoogleTest reported errors")
        for case in cases:
            require(case.get("status") == "run"
                    and case.get("result") == "completed"
                    and not any(case.find(tag) is not None
                                for tag in ("failure", "error", "skipped")),
                    "Incomplete, skipped or failed test: "
                    + case.get("classname", "") + "." + case.get("name", ""))
        summary["tests_passed"] = len(cases)
        summary["test_suites"] = len(list(report.iter("testsuite")))
        summary["passed"] = True
        progress("PASS: GoogleTest results validated")
    except Exception as error:
        summary["error"] = str(error)
        progress("Validation stopped: " + str(error))
    finally:
        if created:
            progress("Removing test container")
            try:
                docker(["rm", "--force", name])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
                summary["passed"] = False
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )

    log = dest / "test.log"
    if log.is_file():
        print("\n=== Last 30 log lines ===")
        for line in log.read_text(errors="replace").splitlines()[-30:]:
            print(line)
    print("\n" + json.dumps(summary, indent=2))
    print("Evidence:", dest)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
