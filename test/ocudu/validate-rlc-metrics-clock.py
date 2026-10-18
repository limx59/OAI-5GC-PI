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
PROGRAM = '\nfrom pathlib import Path\nimport subprocess\nimport sys\nimport xml.etree.ElementTree as ET\n\nsubprocess.run([\n    sys.executable, "-B", "/evidence/patch-ocudu-rlc-metrics-clock.py",\n    "/src/ocudu",\n], check=True)\npath = Path("/src/ocudu/tests/unittests/rlc/rlc_tx_tm_test.cpp")\npath.write_text(path.read_text() + "\\n" +\n                Path("/evidence/rlc-metrics-clock-tests.inc").read_text())\nrx_path = Path("/src/ocudu/tests/unittests/rlc/rlc_rx_tm_test.cpp")\nrx_path.write_text(rx_path.read_text() + "\\n" +\n                   Path("/evidence/rlc-rx-metrics-clock-tests.inc").read_text())\nsubprocess.run([\n    "cmake", "--build", "/build/ocudu", "--target",\n    "rlc_tx_tm_test", "rlc_rx_tm_test", "rlc_bearer_metrics_collector_test",\n    "--parallel", "2",\n], check=True, timeout=1800)\n\ncombined = ET.Element("testsuites")\nfor binary in ("rlc_tx_tm_test", "rlc_rx_tm_test", "rlc_bearer_metrics_collector_test"):\n    xml = Path("/evidence") / (binary + ".xml")\n    subprocess.run([\n        "timeout", "--signal=TERM", "--kill-after=5s", "180s",\n        "/build/ocudu/tests/unittests/rlc/" + binary,\n        "--gtest_output=xml:" + str(xml),\n    ], check=True, timeout=200)\n    combined.extend(list(ET.parse(xml).getroot()))\nET.ElementTree(combined).write("/evidence/results.xml", encoding="utf-8")\n'


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-rlc-metrics-clock-", dir=parent))
    for filename in (
        "patch-ocudu-rlc-metrics-clock.py",
        "rlc-metrics-clock-tests.inc",
        "rlc-rx-metrics-clock-tests.inc",
    ):
        shutil.copyfile(root / "test/ocudu/patches" / filename, dest / filename)
    (dest / "runner.py").write_text(PROGRAM)
    name = "ocudu-rlc-metrics-clock-" + uuid.uuid4().hex[:12]
    docker = ["sudo", "docker"]
    summary = {
        "passed": False,
        "scope": "TX/RX metrics clock isolation and RLC regressions; runtime wiring pending",
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
            "metrics_clock_is_independent_of_protocol_clock",
            "metrics_clock_defaults_to_protocol_clock",
        }
        required.update({
            "rx_metrics_clock_is_independent_of_protocol_clock",
            "rx_metrics_clock_defaults_to_protocol_clock",
        })
        if not required.issubset({case.get("name") for case in cases}):
            raise RuntimeError("Required clock isolation tests are missing")
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
