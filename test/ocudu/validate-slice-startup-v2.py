#!/usr/bin/env python3
"""Validate OCUDU slicing configuration acceptance using isolated dry runs."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ["sudo", "docker"]
EXPECTED_IMAGE_ID = 'sha256:2e750f07d68d00cdf2bdc34c9bfc28f2928e70ea393cbf17b137d218dc063186'
IMAGE = 'limx59/oai-pi-ocudu-config-check:arm64-slicing-test@sha256:2e750f07d68d00cdf2bdc34c9bfc28f2928e70ea393cbf17b137d218dc063186'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def progress(message):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
          + " " + message, flush=True)


def docker(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            "Docker command failed: " + " ".join(args[:2])
            + ": " + result.stderr.strip()
        )
    return result.stdout.strip()


def main():
    parent = ROOT / "test/ocudu/.local/evidence"
    require(parent.resolve().is_relative_to(ROOT),
            "Evidence directory outside repository")
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-slice-startup-v2-", dir=parent))
    dest.chmod(0o700)
    source = ROOT / "deploy/ocudu/config/gnb-zmq-e2.yml"
    require(source.resolve().is_relative_to(ROOT) and source.is_file(),
            "Missing or unexpected base configuration")
    original = source.read_bytes()
    containers = []
    summary = {
        "passed": False,
        "scope": "Configuration acceptance only; no live scheduling validation",
        "network": "none",
        "control_requests_sent": 0,
        "cases": {},
        "cleanup_errors": [],
    }
    progress("Evidence: " + str(dest))
    try:
        helper = ROOT / "test/ocudu/prepare-slice-startup.py"
        require(helper.resolve().is_relative_to(ROOT) and helper.is_file(),
                "Missing or unexpected configuration helper")
        config = dest / "config"
        summary["configuration"] = runpy.run_path(str(helper))["prepare"](
            ROOT, config
        )
        require(summary["configuration"]["source_sha256"]
                == hashlib.sha256(original).hexdigest(),
                "Base configuration changed during generation")

        progress("Checking pinned gNB image")
        image = json.loads(docker(["image", "inspect", IMAGE]))[0]
        require(image["Os"] == "linux"
                and image["Architecture"] == "arm64",
                "Expected linux/arm64 image")
        require(image["Id"] == EXPECTED_IMAGE_ID,
                "Configuration-check image differs from pinned image")
        summary["image"] = {
            "reference": IMAGE, "id": image["Id"],
            "os": image["Os"], "architecture": image["Architecture"],
        }

        for filename, should_pass in (
            ("baseline.yml", True),
            ("two-slices.yml", True),
            ("invalid-min-max.yml", False),
        ):
            label = Path(filename).stem
            name = "ocudu-slice-dryrun-" + uuid.uuid4().hex[:12]
            progress("Dry run: " + filename)
            cid = docker([
                "create", "--pull=never", "--name", name,
                "--network=none", "--ulimit", "core=0:0",
                "--mount",
                "type=bind,source=" + str(config) + ",target=/config,readonly",
                "--entrypoint", "timeout", image["Id"],
                "--signal=TERM", "--kill-after=3s", "30s",
                "/build/ocudu/apps/gnb_split_8/gnb",
                "-c", "/config/" + filename, "--dryrun",
            ])
            containers.append(name)
            with (dest / (label + ".log")).open("w") as stream:
                result = subprocess.run(
                    DOCKER + ["start", "--attach", cid],
                    stdout=stream, stderr=subprocess.STDOUT,
                    text=True, timeout=55,
                )
            state = json.loads(docker(["inspect", cid]))[0]["State"]
            log = (dest / (label + ".log")).read_text(errors="replace")
            summary["cases"][label] = {
                "expected_acceptance": should_pass,
                "attach_returncode": result.returncode,
                "exit_code": state["ExitCode"],
                "oom_killed": state["OOMKilled"],
                "running": state["Running"],
            }
            require(not state["Running"] and not state["OOMKilled"]
                    and not state.get("Error"),
                    label + ": abnormal container state")
            if should_pass:
                require(result.returncode == 0 and state["ExitCode"] == 0,
                        label + ": valid configuration rejected")
                require(log.splitlines().count("LAB_CONFIG_VALIDATION_PASSED") == 1,
                        label + ": validation completion marker missing")
            else:
                require("LAB_CONFIG_VALIDATION_PASSED" not in log,
                        label + ": invalid configuration reached success marker")
                require(0 < state["ExitCode"] < 124
                        and result.returncode != 0,
                        label + ": expected normal validation failure")
                require("expected min_prb_policy_ratio <= max_prb_policy_ratio"
                        in log,
                        label + ": expected min/max diagnostic missing")
            summary["cases"][label]["validated"] = True
            progress("PASS: " + label)
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        progress("Validation stopped: " + str(error))
    finally:
        progress("Cleaning up dry-run containers")
        for name in containers:
            try:
                docker(["rm", "--force", name])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
                summary["passed"] = False
        summary["original_configuration_unchanged"] = (
            source.read_bytes() == original
        )
        if not summary["original_configuration_unchanged"]:
            summary["passed"] = False
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )

    for log in sorted(dest.glob("*.log")):
        print("\n=== " + log.name + ": last 15 lines ===")
        for line in log.read_text(errors="replace").splitlines()[-15:]:
            print(line)
    print("\n" + json.dumps(summary, indent=2))
    print("Evidence:", dest)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
