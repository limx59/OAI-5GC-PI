#!/usr/bin/env python3
"""Run PDCP history/provider C++ tests independently of image builds."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

DEFAULT_IMAGE = (
    "limx59/oai-pi-ocudu-kpm-tests:arm64-pdcp-source-instance-test@sha256:86fd51131dee1645c5e6a2671a8c51eccbbc4d7c2bc91aa59d138f5ce3caa46f"
)
BINARY = (
    "/build/ocudu/tests/unittests/e2/"
    "e2sm_kpm_meas_provider_metrics_test"
)
EXPECTED_SUITES = {
    "pdcp_batch_history_test": 10,
    "pdcp_provider_batch_test": 9,
    "pdcp_source_instance_test": 8,
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def docker(args, timeout=30):
    return subprocess.run(
        ["sudo", "docker", *args],
        capture_output=True, text=True, check=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    ).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()

    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix="ocudu-pdcp-source-instance-unit-", dir=parent))
    name = "ocudu-pdcp-source-unit-" + uuid.uuid4().hex[:12]
    summary = {
        "passed": False,
        "started_utc": utc(),
        "image": args.image,
        "scope": "Ten history, nine provider and eight source-instance C++ tests",
        "limitations": (
            "Real aggregator reconstruction with constructed counters; no live RAN "
            "or KPM wire correlation validation"
        ),
        "cleanup_errors": [],
    }
    created = False
    print(f"Evidence: {dest}", flush=True)

    try:
        metadata = json.loads(docker(["image", "inspect", args.image]))[0]
        summary["image_id"] = metadata["Id"]
        docker([
            "create", "--name", name,
            "--pull", "never", "--network", "none",
            "--mount", f"type=bind,src={dest},dst=/evidence",
            "--entrypoint", BINARY, summary["image_id"],
            "--gtest_filter=pdcp_batch_history_test.*:pdcp_provider_batch_test.*:pdcp_source_instance_test.*",
            "--gtest_output=xml:/evidence/results.xml",
        ])
        created = True

        with (dest / "tests.log").open("x") as stream:
            result = subprocess.run(
                ["sudo", "docker", "start", "-a", name],
                stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, timeout=120,
            )

        container = json.loads(docker(["inspect", name]))[0]
        summary["exit_code"] = container["State"]["ExitCode"]
        summary["actual_image_id"] = container["Image"]
        report = ET.parse(dest / "results.xml").getroot()
        summary["tests"] = int(report.attrib["tests"])
        for key in ("failures", "disabled", "errors"):
            summary[key] = int(report.attrib.get(key, "0"))
        summary["skipped"] = len(report.findall(".//testcase/skipped"))
        summary["suites"] = {
            suite.attrib["name"]: len(suite.findall("testcase"))
            for suite in report.findall("testsuite")
        }
        summary["passed"] = (
            result.returncode == 0
            and not container["State"]["Running"]
            and summary["exit_code"] == 0
            and summary["tests"] == 27
            and summary["suites"] == EXPECTED_SUITES
            and not any(summary[key] for key in (
                "failures", "disabled", "errors", "skipped"))
            and summary["actual_image_id"] == summary["image_id"]
        )
    except KeyboardInterrupt:
        summary["error"] = "Interrupted"
    except Exception as error:
        summary["error"] = str(error)
    finally:
        if created:
            try:
                docker(["rm", "-f", name])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
                summary["passed"] = False
        summary["finished_utc"] = utc()
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
        print(f"Evidence retained: {dest}", flush=True)

    if not summary["passed"]:
        print(f"Inspect failure details: {dest / 'tests.log'}", flush=True)
        raise SystemExit(1)
    print("PASS: all twenty-seven C++ tests; temporary test container removed.")


if __name__ == "__main__":
    main()
