#!/usr/bin/env python3
"""Run the OCUDU PHY concurrency comparison with an explicit main-pool worker count."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BASELINE_IMAGE = "limx59/oai-pi-ocudu-gnb:arm64-steering-prb-kpm-metadata-v2-test"
RUNNER_COMPOSE = "deploy/ocudu/compose.session-stability-runner.yaml"
DIAG_COMPOSE = "deploy/ocudu/compose.phy-concurrency-diag.yaml"
VALIDATOR = "test/ocudu/validate-session-stability.py"
SESSION_COMPOSE = "deploy/ocudu/compose.session-stability.yaml"
PREPARE = "test/ocudu/prepare-session-stability.py"


def docker_output(*args):
    return subprocess.check_output(["sudo", "docker", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-pool-workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    resolved = json.loads(docker_output(
        "compose", "-f", str(ROOT / DIAG_COMPOSE), "config", "--format", "json"
    ))
    image = resolved["services"]["gnb"]["image"]
    name, separator, tag = image.rpartition(":")
    if ("@" in image or not separator or not name or name == "sha256"
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag)):
        raise SystemExit("STOP: diagnostic Compose requires an image name and explicit tag")

    platform = docker_output(
        "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image
    )
    if platform != "linux/arm64":
        raise SystemExit(f"STOP: unexpected platform for {image}: {platform}")

    running = docker_output("ps", "--format", "{{.Names}}")
    active = [
        name for name in running.splitlines()
        if re.match(r"^ocudu-session-(?:[0-9a-f]+-|.*session-test-run-)", name)
    ]
    if active:
        raise SystemExit("STOP: a session test is already running: " + ", ".join(active))

    with tempfile.TemporaryDirectory(prefix="ocudu-phy-diag-") as directory:
        mounts = []
        paths = [VALIDATOR, SESSION_COMPOSE]
        if args.main_pool_workers == 1:
            paths.append(PREPARE)
        for relative_path in paths:
            original = ROOT / relative_path
            text = original.read_text(encoding="utf-8")
            if relative_path == PREPARE:
                replacements = (
                    ("Explicit two-worker main pool", "Explicit one-worker main pool"),
                    ("nof_threads: 2", "nof_threads: 1"),
                    ('"main_pool_threads": 2', '"main_pool_threads": 1'),
                )
            else:
                replacements = [(BASELINE_IMAGE, image)]
                if relative_path == VALIDATOR:
                    replacements.append(
                        ("deadline = time.monotonic() + 90", "deadline = time.monotonic() + 20")
                    )

            updated = text
            for old, new in replacements:
                if updated.count(old) != 1:
                    raise SystemExit(f"STOP: expected one match for {old!r} in {original}")
                updated = updated.replace(old, new, 1)
            if original.suffix == ".py":
                compile(updated, str(original), "exec")

            override = Path(directory) / original.name
            override.write_text(updated, encoding="utf-8")
            mounts.extend(("-v", f"{override}:{original}:ro"))

        readiness = 20
        print(
            f"PASS: preflight for {image} ({platform}), "
            f"main_pool={args.main_pool_workers}, readiness={readiness}s",
            flush=True,
        )
        if args.check_only:
            return 0

        command = [
            "sudo", "--preserve-env=OCUDU_SESSION_ROOT", "docker", "compose",
            "-p", f"ocudu-session-phy-diag-{args.main_pool_workers}w",
            "-f", RUNNER_COMPOSE,
            "run", "-T", "--rm", "--no-deps", "--pull", "never",
            *mounts,
            "session-test", "--duration-seconds", "60", "--interval-seconds", "60",
        ]
        return subprocess.run(
            command, cwd=ROOT, env={**os.environ, "OCUDU_SESSION_ROOT": str(ROOT)}
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
