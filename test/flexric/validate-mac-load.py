#!/usr/bin/env python3
"""Validate controlled emulator MAC loads on an existing multi-RIC lab."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def decode(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-mac-load-baseline"))
    parser.add_argument("--use-image-code", action="store_true",
                        help="Use packaged Python code without host mounts.")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence directory: {output}", flush=True)

    root = Path(__file__).resolve().parents[2]
    docker = ["sudo", "docker"]
    compose = docker + ["compose"]
    for filename in (
        "compose.emulator.yaml", "compose.multi-agent.yaml",
        "compose.multi-ric.yaml", "compose.steering-load.yaml",
    ):
        compose += ["-f", str(root / "deploy/oai-flexric" / filename)]

    summary = {"model": "controlled_emulator", "passed": False, "rics": {}}
    try:
        for label, service, expected in (
            ("ric-a", "xapp-kpm", {1: 0.9, 2: 0.2}),
            ("ric-b", "xapp-kpm-ric2", {3: 0.4}),
        ):
            command = compose + [
                "--profile", "tools", "run", "-T", "--rm",
                "--no-deps", "--pull", "never",
            ]
            filenames = () if args.use_image_code else (
                "xapp_mac_load.py", "xapp_radio_stats.py")
            for filename in filenames:
                source = root / "test/xapp" / filename
                require(source.is_file(), f"Missing source: {source}")
                command += [
                    "-v", f"{source}:/opt/oai-pi/test/xapp/{filename}:ro",
                ]
            command += [
                service, "xapp_mac_load.py",
                "-c", "/usr/local/etc/flexric/xapp.conf",
            ]
            path = output / f"{label}.log"
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True,
                    stdin=subprocess.DEVNULL, timeout=45)
            except subprocess.TimeoutExpired as error:
                path.write_text(
                    decode(error.stdout) + decode(error.stderr), encoding="utf-8")
                raise RuntimeError(
                    f"{label}: timeout; inspect remaining containers and {path}") from error

            text = result.stdout + result.stderr
            path.write_text(text, encoding="utf-8")
            require(result.returncode == 0, f"{label}: abnormal exit; inspect {path}")
            require(not any(marker in text for marker in (
                "callback error:", "Traceback", "Assertion", "DirectorMethodException",
            )), f"{label}: error in {path}")
            reports = [
                json.loads(line[6:]) for line in text.splitlines()
                if line.startswith("LOAD: ")
            ]
            require({row["node"] for row in reports} == set(expected),
                    f"{label}: unexpected node set")
            counts = {}
            for node, load in expected.items():
                rows = [row for row in reports if row["node"] == node]
                require(len(rows) >= 5, f"{label}: node {node}: insufficient reports")
                require(all(
                    row["model"] == "controlled_emulator"
                    and abs(row[metric] - load) < 0.01
                    for row in rows for metric in ("dl", "ul")
                ), f"{label}: node {node}: unexpected load")
                counts[node] = len(rows)
                print(f"PASS: node={node}, reports={len(rows)}, "
                      f"expected DL/UL={load:.0%}", flush=True)
            deletes = text.count("E42 SUBSCRIPTION DELETE RESPONSE rx")
            require(deletes == len(expected), f"{label}: incomplete subscription cleanup")
            summary["rics"][label] = {
                "expected_loads": expected, "report_counts": counts,
                "exit_code": result.returncode, "delete_responses": deletes,
            }
            print(f"PASS: {label} exit and subscription cleanup", flush=True)

        names = [
            "oai-pi-flexric-lab-ric-1", "oai-pi-flexric-lab-ric-2-1",
            "oai-pi-flexric-lab-emulator-1",
            "oai-pi-flexric-lab-emulator-2-1",
            "oai-pi-flexric-lab-emulator-3-1",
        ]
        result = subprocess.run(
            docker + ["inspect", *names], capture_output=True, text=True,
            stdin=subprocess.DEVNULL, check=True, timeout=30)
        (output / "lab-after.json").write_text(result.stdout, encoding="utf-8")
        require(all(
            item["State"]["Running"] and not item["State"]["Paused"]
            for item in json.loads(result.stdout)
        ), "Lab containers are not running normally")
        summary["passed"] = True
        print("PASS: controlled MAC load baseline; lab remains running", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {output}", flush=True)


if __name__ == "__main__":
    main()
