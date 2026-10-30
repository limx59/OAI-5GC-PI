#!/usr/bin/env python3
"""Run isolated real-AUSF routing regression through Docker Compose."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


DOCKER = ["sudo", "docker"]
IMAGES = {
    "control": "docker_open5gs:local-arm64",
    "patched": "limx59/open5gs-ausf:arm64-stale-nf-reference-test@sha256:7ba6049f69cde00ba19eb19319020ea7d3d078b040bd0ecf122398f8fa96f3c4",
    "fixture": "limx59/open5gs-ausf-tests:arm64-stale-nf-reference-test@sha256:937d3daf3a33dba7a9d6a3cfabe52288cc7d3eb0c1c257a9999beca901ca4eb1",
}
BASELINE = (
    "ausf", "udm", "udr", "nrf", "scp", "amf", "smf", "upf",
    "oai-pi-ocudu-zmq-lab-ric-1",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, timeout=30):
    return subprocess.check_output(
        DOCKER + args, text=True, timeout=timeout,
    ).strip()


def identities():
    result = {}
    for name in BASELINE:
        value = json.loads(command(["inspect", name]))[0]
        result[name] = {
            "id": value["Id"],
            "image": value["Image"],
            "pid": value["State"]["Pid"],
            "started": value["State"]["StartedAt"],
            "restarts": value["RestartCount"],
            "running": value["State"]["Running"],
        }
    return result


def main():
    root = Path(__file__).resolve().parents[2]
    compose_file = root / "deploy/open5gs/compose.ausf-stale-nf-reference-v2.yaml"
    parent = root / "test/open5gs/.local/evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ausf-stale-nf-routing-", dir=parent))
    dest.chmod(0o700)
    print("Evidence:", dest, flush=True)

    project = "ausf-routing-" + uuid.uuid4().hex[:12]
    compose = [
        "compose", "--project-name", project,
        "--env-file", str(dest / "compose.env"),
        "-f", str(compose_file),
    ]
    result = {
        "passed": False,
        "cleanup_errors": [],
        "scope": "Isolated real AUSF binaries with synthetic HTTP/2 peers",
        "real_ue_authentication_validated": False,
        "real_nrf_heartbeat_recovery_validated": False,
        "project": project,
    }
    touched = False
    try:
        result["baseline_before"] = identities()
        require(all(item["running"] for item in result["baseline_before"].values()),
                "Expected baseline service is not running")

        image_ids = {}
        for label, image in IMAGES.items():
            value = json.loads(command(["image", "inspect", image]))[0]
            require(value["Architecture"] == "arm64",
                    "Unexpected architecture: " + label)
            image_ids[label] = value["Id"]
        result["image_ids"] = image_ids
        require(image_ids["control"] == "sha256:69d576e04d6e5a094b8c0e37e69bc1ba173dfa23bbfaf4de712f5959b5f04edd",
                "Control image differs from reviewed original runtime")

        env = dest / "compose.env"
        env.write_text(
            f"AUSF_ROUTING_EVIDENCE={dest}\n"
            f"AUSF_ROUTING_UID={os.getuid()}\n"
            f"AUSF_ROUTING_GID={os.getgid()}\n"
            f"AUSF_CONTROL_IMAGE={IMAGES['control']}\n"
            f"AUSF_PATCHED_IMAGE={IMAGES['patched']}\n"
        )
        env.chmod(0o600)
        resolved = json.loads(command(compose + ["config", "--format", "json"]))
        require(set(resolved["services"]) == {
            "fixture", "ausf-control", "ausf-patched", "check",
        }, "Unexpected Compose service set")
        require(all(
            network.get("internal") and not network.get("external")
            for network in resolved["networks"].values()
        ), "Test network must be internal and independent")
        for service in resolved["services"].values():
            require(not service.get("ports"), "Host ports must not be published")
            require(not service.get("network_mode"),
                    "Unexpected shared network namespace")
            require(not service.get("pid"), "Unexpected shared PID namespace")
            require(not service.get("privileged"), "Privileged service rejected")
        (dest / "compose.resolved.json").write_text(
            json.dumps(resolved, indent=2) + "\n"
        )

        print("RUNNING: isolated Compose control/patched regression", flush=True)
        touched = True
        with (dest / "compose-run.log").open("w") as log:
            run = subprocess.run(
                DOCKER + compose + [
                    "up", "--no-build", "--abort-on-container-exit",
                    "--exit-code-from", "check",
                ],
                stdout=log, stderr=subprocess.STDOUT, timeout=240,
            )
        result["compose_exit_code"] = run.returncode
        acceptance = dest / "routing-summary.json"
        require(acceptance.is_file(),
                "Routing summary missing; inspect retained Compose log")
        result["routing"] = json.loads(acceptance.read_text())
        require(run.returncode == 0 and result["routing"]["passed"],
                "Routing regression failed; inspect retained evidence")
    except Exception as error:
        result["error"] = str(error)
    finally:
        if touched:
            try:
                logs = command(compose + ["logs", "--no-color"], timeout=30)
                (dest / "services.log").write_text(logs)
            except Exception as error:
                result["diagnostic_error"] = str(error)
            try:
                subprocess.run(
                    DOCKER + compose + ["down", "--timeout", "5"],
                    check=True, timeout=60,
                )
                remaining = command([
                    "ps", "-a", "-q", "--filter",
                    "label=com.docker.compose.project=" + project,
                ])
                require(not remaining, "Test containers remain after cleanup")
            except Exception as error:
                result["cleanup_errors"].append(str(error))
        if "baseline_before" in result:
            try:
                result["baseline_after"] = identities()
                require(result["baseline_before"] == result["baseline_after"],
                        "Baseline service identities changed")
            except Exception as error:
                result["baseline_error"] = str(error)

        result["passed"] = (
            result.get("routing", {}).get("passed", False)
            and result.get("compose_exit_code") == 0
            and not result["cleanup_errors"]
            and "error" not in result
            and "baseline_error" not in result
        )
        (dest / "summary.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(json.dumps(result, indent=2), flush=True)
        print("Evidence retained:", dest, flush=True)

    if not result["passed"]:
        raise SystemExit(1)
    print("PASS: isolated routing recovery; baseline retained; cleanup complete.")


if __name__ == "__main__":
    main()
