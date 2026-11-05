#!/usr/bin/env python3
"""Check parsed DU testmode states through isolated Compose dry runs."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ["sudo", "docker"]
IMAGE = "limx59/oai-pi-ocudu-testmode-state:arm64-config-state-test"
MARKER = re.compile(
    r"^LAB_TESTMODE_STATE du_enabled=(true|false) du_rnti=(\d+) "
    r"cu_up_enabled=(true|false) no_core=(true|false)$", re.M,
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        timeout=timeout, stdin=subprocess.DEVNULL,
    )
    require(result.returncode == 0,
            "Docker operation failed: " + (result.stdout + result.stderr)[-2000:])
    return result.stdout.strip()


def save(path, value):
    with path.open("x") as stream:
        path.chmod(0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")


def identities(ids):
    if not ids:
        return {}
    return {
        item["Id"]: {
            "image": item["Image"], "pid": item["State"]["Pid"],
            "started": item["State"]["StartedAt"],
            "restarts": item["RestartCount"],
            "running": item["State"]["Running"],
            "oom_killed": item["State"]["OOMKilled"],
        }
        for item in json.loads(run(["inspect", *ids]))
    }


def main():
    source = ROOT / "deploy/ocudu/config/gnb-zmq.yml"
    original = source.read_bytes()
    require(not re.search(r"(?m)^test_mode\s*:", original.decode()),
            "Base configuration already contains test_mode")
    base = ROOT / "test/ocudu/.local/evidence"
    base.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-testmode-state-", dir=base))
    dest.chmod(0o700)
    report = {
        "passed": False,
        "scope": "Parsed/autoderived state only; exits before initialization",
        "cases": {}, "cleanup_errors": [],
        "live_test_ue_creation_validated": False,
        "source_sha256": hashlib.sha256(original).hexdigest(),
    }
    baseline = None
    print("Evidence:", dest, flush=True)
    try:
        baseline = identities(run(["ps", "-q", "--no-trunc"]).split())
        report["baseline_before"] = baseline
        image = json.loads(run(["image", "inspect", IMAGE]))[0]
        require(image["Architecture"] == "arm64" and image["Os"] == "linux",
                "Unexpected image platform")
        report["image"] = {"reference": IMAGE, "id": image["Id"]}
        cases = (
            ("default", "", (False, 0, False, False)),
            ("explicit-disabled",
             "\ntest_mode:\n  test_ue:\n    rnti: 0\n",
             (False, 0, False, False)),
            ("du-enabled",
             "\ntest_mode:\n  test_ue:\n    rnti: 17921\n",
             (True, 17921, False, True)),
            ("cu-up-disabled", "", (False, 0, False, False)),
            ("cu-up-enabled", "", (False, 0, True, False)),
            ("both-enabled",
             "\ntest_mode:\n  test_ue:\n    rnti: 17921\n",
             (True, 17921, True, True)),
            ("retained-real-ue", "", (False, 0, False, False)),
        )
        for name, suffix, expected in cases:
            case = dest / name
            case.mkdir(mode=0o700)
            config = case / "gnb.yml"
            case_text = original.decode() + suffix
            if name == "retained-real-ue":
                retained = (
                    ROOT / "test/ocudu/.local/evidence/"
                    "ocudu-slice-online-ul-drain-xadw8l91"
                )
                retained_summary = json.loads(
                    (retained / "summary.json").read_text()
                )
                retained_config = (retained / "config/gnb.yml").read_bytes()
                expected_hash = retained_summary["configuration"]["generated_sha256"]
                require(retained_summary.get("passed") is True
                        and hashlib.sha256(retained_config).hexdigest() == expected_hash,
                        "Retained real-UE configuration evidence mismatch")
                case_text = retained_config.decode()
                report["retained_real_ue"] = {
                    "evidence": retained.name,
                    "configuration_sha256": expected_hash,
                    "ue_address": retained_summary["ue_address"],
                    "scope": "Original configuration replay; not a new UE run",
                }
            if name in ("cu-up-disabled", "cu-up-enabled", "both-enabled"):
                anchor = "cu_up:\n"
                require(case_text.count(anchor) == 1,
                        "Expected one CU-UP configuration section")
                enabled = "false" if name == "cu-up-disabled" else "true"
                case_text = case_text.replace(
                    anchor,
                    anchor + "  test_mode:\n    enable: " + enabled + "\n",
                    1,
                )
            config.write_text(case_text)
            config.chmod(0o600)
            env = case / "compose.env"
            env.write_text(
                f"TESTMODE_CONFIG={config}\n"
                f"TESTMODE_UID={os.getuid()}\n"
                f"TESTMODE_GID={os.getgid()}\n"
            )
            env.chmod(0o600)
            project = "ocudu-testmode-" + uuid.uuid4().hex[:10]
            compose = [
                "compose", "--project-name", project, "--env-file", str(env),
                "-f", str(ROOT / "deploy/ocudu/compose.testmode-state.yaml"),
            ]
            try:
                resolved = json.loads(run(
                    compose + ["config", "--format", "json"]
                ))
                require(set(resolved["services"]) == {"testmode-state"},
                        "Unexpected services")
                service = resolved["services"]["testmode-state"]
                require(service["image"] == IMAGE
                        and service["network_mode"] == "none"
                        and service["user"] == f"{os.getuid()}:{os.getgid()}"
                        and service["read_only"] is True
                        and not service.get("ports")
                        and not service.get("devices")
                        and service["command"] == [
                            "/build/ocudu/apps/gnb_split_8/gnb",
                            "-c", "/config/gnb.yml", "--dryrun",
                        ]
                        and len(service["volumes"]) == 1
                        and service["volumes"][0]["read_only"] is True
                        and Path(service["volumes"][0]["source"]) == config,
                        "Unexpected dry-run isolation")
                run(compose + [
                    "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                    "testmode-state",
                ], timeout=60)
                cid = run(compose + ["ps", "--all", "-q", "testmode-state"])
                require(cid and len(cid.splitlines()) == 1, "Missing service")
                deadline = time.monotonic() + 30
                while True:
                    item = json.loads(run(["inspect", cid]))[0]
                    if not item["State"]["Running"]:
                        break
                    require(time.monotonic() < deadline, "Dry-run timed out")
                    time.sleep(0.1)
                logs = subprocess.run(
                    DOCKER + ["logs", cid], capture_output=True,
                    text=True, timeout=20,
                )
                require(logs.returncode == 0, "Could not retain service logs")
                for stream in ("stdout", "stderr"):
                    path = case / (stream + ".log")
                    path.write_text(getattr(logs, stream))
                    path.chmod(0o600)
                output = logs.stdout + logs.stderr
                save(case / "container.json", {
                    "id": cid, "image": item["Image"],
                    "exit_code": item["State"]["ExitCode"],
                    "oom_killed": item["State"]["OOMKilled"],
                    "restarts": item["RestartCount"],
                })
                require(item["Image"] == image["Id"]
                        and item["State"]["ExitCode"] == 0
                        and not item["State"]["OOMKilled"]
                        and item["RestartCount"] == 0,
                        "Dry-run failed: " + name)
                matches = MARKER.findall(output)
                require(len(matches) == 1
                        and output.count("LAB_CONFIG_VALIDATION_PASSED") == 1,
                        "Missing or duplicated validation/state marker")
                du, rnti, cu_up, no_core = matches[0]
                actual = (du == "true", int(rnti),
                          cu_up == "true", no_core == "true")
                require(actual == expected, "Unexpected parsed state: " + name)
                report["cases"][name] = {
                    "passed": True,
                    "configuration_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                    "du_enabled": actual[0], "du_rnti": actual[1],
                    "cu_up_enabled": actual[2], "no_core": actual[3],
                }
                print("PASS:", name, actual, flush=True)
            finally:
                try:
                    run(compose + ["down"], timeout=60)
                    require(not run([
                        "ps", "-a", "-q", "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]), "Test containers remain")
                except Exception as error:
                    report["cleanup_errors"].append(str(error))
        require(source.read_bytes() == original, "Base configuration changed")
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        if baseline is not None:
            try:
                report["baseline_after"] = identities(list(baseline))
                require(report["baseline_after"] == baseline,
                        "Baseline processes changed")
            except Exception as error:
                report["cleanup_errors"].append(str(error))
        if report["cleanup_errors"]:
            report["passed"] = False
        save(dest / "summary.json", report)
    print(json.dumps({
        "passed": report["passed"],
        "error": report.get("error"),
        "cases": report["cases"],
        "cleanup_errors": report["cleanup_errors"],
    }, indent=2))
    print("Evidence:", dest)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
