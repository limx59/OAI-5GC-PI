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
PROGRAM = '\nfrom pathlib import Path\nimport subprocess\nimport sys\nimport xml.etree.ElementTree as ET\n\nfor patch in (\n    "patch-ocudu-kpm-rlc-revisions.py",\n    "patch-ocudu-kpm-revision-interface.py",\n    "patch-ocudu-kpm-style4-freshness.py",\n):\n    subprocess.run([\n        sys.executable, "-B", "/evidence/" + patch, "/src/ocudu",\n    ], check=True)\n\nfor filename, fragment in (\n    ("e2sm_kpm_meas_provider_metrics_test.cpp", "kpm-rlc-revisions-tests.inc"),\n    ("e2sm_kpm_test.cpp", "kpm-style4-freshness-tests.inc"),\n):\n    path = Path("/src/ocudu/tests/unittests/e2") / filename\n    path.write_text(path.read_text() + "\\n" +\n                    (Path("/evidence") / fragment).read_text())\n\nsubprocess.run([\n    "cmake", "--build", "/build/ocudu", "--target",\n    "e2sm_kpm_meas_provider_metrics_test", "e2sm_kpm_test",\n    "--parallel", "1",\n], check=True, timeout=1800)\n\ncombined = ET.Element("testsuites")\nfor binary, xml, filters in (\n    ("e2sm_kpm_meas_provider_metrics_test", "provider.xml", []),\n    ("e2sm_kpm_test", "reports.xml", [\n        "--gtest_filter=e2sm_kpm_collection_lock.*:"\n        "e2sm_kpm_style4_record_guard.*:"\n        "e2sm_kpm_report_service_style2_test.*:"\n        "*e2sm_kpm_generates_ric_indication_style4*:"\n        "e2sm_kpm_style4_freshness.*"\n    ]),\n):\n    subprocess.run([\n        "timeout", "--signal=TERM", "--kill-after=5s", "180s",\n        "/build/ocudu/tests/unittests/e2/" + binary,\n        "--gtest_output=xml:/evidence/" + xml,\n    ] + filters, check=True, timeout=200)\n    report = ET.parse(Path("/evidence") / xml).getroot()\n    combined.extend(list(report))\nET.ElementTree(combined).write("/evidence/results.xml", encoding="utf-8")\n'


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-kpm-freshness-", dir=parent))
    shutil.copyfile(
        root / "test/ocudu/patches/patch-ocudu-kpm-rlc-revisions.py",
        dest / "patch-ocudu-kpm-rlc-revisions.py",
    )
    shutil.copyfile(
        root / "test/ocudu/patches/kpm-rlc-revisions-tests.inc",
        dest / "kpm-rlc-revisions-tests.inc",
    )
    for filename in (
        "patch-ocudu-kpm-revision-interface.py",
        "patch-ocudu-kpm-style4-freshness.py",
        "kpm-style4-freshness-tests.inc",
    ):
        shutil.copyfile(root / "test/ocudu/patches" / filename, dest / filename)
    (dest / "runner.py").write_text(PROGRAM)
    name = "ocudu-kpm-freshness-" + uuid.uuid4().hex[:12]
    docker = ["sudo", "docker"]
    summary = {
        "passed": False,
        "scope": "Style 4 throughput duplicate suppression; runtime cadence and source age not validated",
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
        required.update({
            "duplicate_samples_are_unavailable_and_new_samples_recover",
            "subscriptions_do_not_consume_each_others_samples",
            "failed_collection_does_not_commit_revisions",
        })
        if len(cases) != 26 or not required.issubset(
            {case.get("name") for case in cases}
        ):
            raise RuntimeError("Expected 26 tests including revision and subscription checks")
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
