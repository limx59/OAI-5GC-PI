#!/usr/bin/env python3
"""Run packaged common-metric and policy acceptance through Compose."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

IMAGE = "limx59/oai-pi-ocudu-flexric-xapp:arm64-steering-common-metrics-test@sha256:03896a15ca9448c1613f66a9196e4bd265c0ec4965817b1096dcb9bc7b36c40b"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oai-csv", type=Path, required=True)
    parser.add_argument("--ocudu-csv", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    inputs = {
        "oai": args.oai_csv.resolve(),
        "ocudu": args.ocudu_csv.resolve(),
    }
    for source in inputs.values():
        require(source.is_file(), f"Input missing: {source}")
        require("\n" not in str(source) and "\r" not in str(source),
                "Invalid input path")
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="steering-common-compose-", dir=parent))
    print(f"Evidence: {dest}", flush=True)
    before = {
        system: hashlib.sha256(source.read_bytes()).hexdigest()
        for system, source in inputs.items()
    }
    env_file = dest / "compose.env"
    env_file.write_text(
        f"STEERING_OAI_CSV={inputs['oai']}\n"
        f"STEERING_OCUDU_CSV={inputs['ocudu']}\n"
        f"STEERING_COMMON_EVIDENCE={dest}\n"
        f"STEERING_COMMON_IMAGE={IMAGE}\n"
    )
    command = [
        "sudo", "docker", "compose",
        "--project-name", "steering-common-" + uuid.uuid4().hex[:12],
        "--env-file", str(env_file), "-f",
        str(root / "deploy/ocudu/compose.steering-common-metrics.yaml"),
    ]
    summary = {"passed": False, "cleanup_errors": [], "input_sha256": before}
    try:
        metadata = subprocess.check_output(
            ["sudo", "docker", "image", "inspect", IMAGE],
            text=True, timeout=30,
        )
        (dest / "image.json").write_text(metadata)
        summary["image"] = IMAGE
        summary["image_id"] = json.loads(metadata)[0]["Id"]
        resolved = subprocess.check_output(
            command + ["config", "--format", "json"], text=True, timeout=30,
        )
        (dest / "compose.resolved.json").write_text(resolved)
        service = json.loads(resolved)["services"]["steering-common-metrics"]
        require(service["network_mode"] == "none"
                and service["image"] == IMAGE, "Unexpected Compose configuration")
        for target in ("/inputs/oai.csv", "/inputs/ocudu.csv"):
            mounts = [m for m in service["volumes"] if m["target"] == target]
            require(len(mounts) == 1 and mounts[0].get("read_only"),
                    "Input mount must be read-only")
        with (dest / "stdout.log").open("w") as out, \
             (dest / "stderr.log").open("w") as err:
            result = subprocess.run(
                command + [
                    "up", "--no-build", "--pull", "never",
                    "--abort-on-container-exit", "--exit-code-from",
                    "steering-common-metrics",
                ],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=90,
            )
        require(result.returncode == 0, "Compose acceptance failed; inspect logs")
        result = json.loads((dest / "result/summary.json").read_text())
        require(result["passed"], "Packaged acceptance failed")
        policy = root / "test/xapp/xapp_traffic_steering.py"
        require(result["policy_sha256"]
                == hashlib.sha256(policy.read_bytes()).hexdigest(),
                "Packaged policy differs from repository source")
        for system, source in inputs.items():
            require(result["inputs"][system]["sha256"] == before[system],
                    "Container consumed unexpected input")
            require(hashlib.sha256(source.read_bytes()).hexdigest()
                    == before[system], "Input evidence changed")
        summary["acceptance"] = result
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
    finally:
        try:
            cleaned = subprocess.run(
                command + ["down"], capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=30,
            )
            (dest / "cleanup.log").write_text(cleaned.stdout + cleaned.stderr)
            require(cleaned.returncode == 0, "Compose cleanup failed")
            remaining = subprocess.check_output(
                command + ["ps", "--all", "--quiet"], text=True, timeout=30,
            )
            require(not remaining.strip(), "Test containers remain")
        except Exception as error:
            summary["cleanup_errors"].append(str(error))
            summary["passed"] = False
        (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
        print(f"Evidence retained: {dest}", flush=True)
    if not summary["passed"]:
        raise SystemExit(1)
    print("PASS: packaged common metrics and cooldown rules; cleanup complete.")


if __name__ == "__main__":
    main()
