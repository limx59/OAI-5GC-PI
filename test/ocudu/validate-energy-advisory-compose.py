#!/usr/bin/env python3
"""Run the fixture-based energy advisory service through Docker Compose."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ["sudo", "docker"]


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


def main():
    base = ROOT / "test/ocudu/.local/evidence"
    base.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-energy-advisory-", dir=base))
    dest.chmod(0o700)
    results = dest / "results"
    results.mkdir(mode=0o700)
    source = ROOT / "test/xapp/energy_samples.json"
    snapshot = dest / "input.json"
    snapshot.write_bytes(source.read_bytes())
    snapshot.chmod(0o600)
    env = dest / "compose.env"
    env.write_text(
        f"ENERGY_UID={os.getuid()}\n"
        f"ENERGY_GID={os.getgid()}\n"
        f"ENERGY_INPUT={snapshot}\n"
        f"ENERGY_EVIDENCE={results}\n"
    )
    env.chmod(0o600)
    project = "ocudu-energy-" + uuid.uuid4().hex[:10]
    compose = [
        "compose", "--project-name", project, "--env-file", str(env),
        "-f", str(ROOT / "deploy/ocudu/compose.energy-advisory.yaml"),
    ]
    report = {
        "passed": False, "cleanup_errors": [],
        "scope": "Compose fixture-based energy advice and state simulation",
        "real_control_executed": False,
        "power_saving_measured": False,
    }
    baseline = None
    print("Evidence:", dest, flush=True)

    def identities(ids):
        if not ids:
            return {}
        return {
            item["Id"]: {
                "image": item["Image"],
                "pid": item["State"]["Pid"],
                "started": item["State"]["StartedAt"],
                "restarts": item["RestartCount"],
                "running": item["State"]["Running"],
                "oom_killed": item["State"]["OOMKilled"],
            }
            for item in json.loads(run(["inspect", *ids]))
        }

    try:
        baseline = identities(run(["ps", "-q", "--no-trunc"]).split())
        report["baseline_before"] = baseline
        resolved = json.loads(run(compose + ["config", "--format", "json"]))
        require(set(resolved["services"]) == {"energy-advisor"},
                "Unexpected service set")
        service = resolved["services"]["energy-advisor"]
        mounts = {v["target"]: v for v in service.get("volumes", [])}
        require(
            service["image"] ==
                "limx59/oai-pi-ocudu-energy-advisor:arm64-state-simulation-test"
            and service["pull_policy"] == "never"
            and service["network_mode"] == "none"
            and service["read_only"] is True
            and service["user"] == f"{os.getuid()}:{os.getgid()}"
            and not service.get("ports")
            and set(mounts) == {"/config/energy_samples.json", "/evidence"}
            and mounts["/config/energy_samples.json"].get("read_only") is True
            and Path(mounts["/config/energy_samples.json"]["source"]) == snapshot
            and Path(mounts["/evidence"]["source"]) == results,
            "Unexpected service isolation or mounts",
        )
        image = json.loads(run(["image", "inspect", service["image"]]))[0]
        require(image["Architecture"] == "arm64" and image["Os"] == "linux",
                "Unexpected image platform")
        report["image"] = {"reference": service["image"], "id": image["Id"]}
        run(compose + [
            "up", "-d", "--no-deps", "--no-build", "--pull", "never",
            "energy-advisor",
        ], timeout=60)
        cid = run(compose + ["ps", "--all", "-q", "energy-advisor"])
        require(cid and len(cid.splitlines()) == 1, "Missing service")
        deadline = time.monotonic() + 30
        while True:
            item = json.loads(run(["inspect", cid]))[0]
            if not item["State"]["Running"]:
                break
            require(time.monotonic() < deadline, "Simulation timed out")
            time.sleep(0.1)
        logs = subprocess.run(
            DOCKER + ["logs", cid], capture_output=True, text=True, timeout=20,
        )
        log_path = dest / "service.log"
        log_path.write_text(logs.stdout + logs.stderr)
        log_path.chmod(0o600)
        report["container"] = {
            "id": cid, "image": item["Image"],
            "exit_code": item["State"]["ExitCode"],
            "oom_killed": item["State"]["OOMKilled"],
            "restarts": item["RestartCount"],
        }
        require(item["Image"] == image["Id"]
                and item["State"]["ExitCode"] == 0
                and not item["State"]["OOMKilled"]
                and item["RestartCount"] == 0,
                "Unexpected container outcome")
        report["result"] = json.loads((results / "summary.json").read_text())
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        try:
            run(compose + ["down"], timeout=60)
            require(not run(["ps", "-a", "-q", "--filter",
                             "label=com.docker.compose.project=" + project]),
                    "Test containers remain")
        except Exception as error:
            report["cleanup_errors"].append(str(error))
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

    if report["passed"]:
        try:
            review = runpy.run_path(str(
                ROOT / "test/ocudu/review-energy-advisory.py"
            ))["review"]
            checked = review(dest)
            save(dest / "independent-review.json", checked)
        except Exception as error:
            report["passed"] = False
            report["review_error"] = str(error)
            (dest / "summary.json").write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps({
        "passed": report["passed"],
        "error": report.get("error"),
        "review_error": report.get("review_error"),
        "cleanup_errors": report["cleanup_errors"],
        "real_control_executed": False,
        "power_saving_measured": False,
    }, indent=2))
    print("Evidence:", dest)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
