#!/usr/bin/env python3
"""Validate live steering recommendations from controlled emulator MAC load."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-live-steering"))
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
    name = "live-steering-" + uuid.uuid4().hex[:10]
    lab = [
        "oai-pi-flexric-lab-ric-1", "oai-pi-flexric-lab-ric-2-1",
        "oai-pi-flexric-lab-emulator-1",
        "oai-pi-flexric-lab-emulator-2-1",
        "oai-pi-flexric-lab-emulator-3-1",
    ]
    directory = root / "deploy/oai-flexric/config/steering-load"
    originals = {
        directory / f"node-{node}.txt":
        (directory / f"node-{node}.txt").read_bytes()
        for node in (1, 2, 3)
    }
    summary = {"passed": False, "model": "controlled_emulator"}
    created = False
    sequence = 0

    def run(command, label, timeout=30):
        nonlocal sequence
        sequence += 1
        path = output / f"{sequence:03d}-{label}.log"
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decode(value):
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            path.write_text(decode(error.stdout) + decode(error.stderr),
                            encoding="utf-8")
            raise RuntimeError(f"{label}: timeout; inspect {path}") from error
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0, f"{label}: failed; inspect {path}")
        return result.stdout

    def inspect(names, label):
        return json.loads(run(docker + ["inspect", *names], label))

    def identity(item):
        return (item["Id"], item["State"]["StartedAt"],
                item["State"]["Pid"], item["RestartCount"])

    def set_loads(values):
        for node, percent in values.items():
            path = directory / f"node-{node}.txt"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(f"{percent}\n", encoding="utf-8")
            temporary.replace(path)

    def rows():
        # docker logs emits application stdout on stdout.
        text = run(docker + ["logs", name], "xapp-poll")
        require(not any(marker in text for marker in (
            "callback error:", "Traceback", "Assertion", "DirectorMethodException",
        )), "Error in xApp output")
        return [
            json.loads(line[10:]) for line in text.splitlines()
            if line.startswith("STEERING: ")
        ]

    def wait_for(predicate, label, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = rows()
            if predicate(current):
                return current
            state = inspect([name], "xapp-state")[0]
            require(state["State"]["Running"], f"{label}: xApp exited early")
            time.sleep(0.5)
        raise RuntimeError(f"{label}: condition not reached")

    try:
        before = inspect(lab, "lab-before")
        require(all(item["State"]["Running"] and not item["State"]["Paused"]
                    for item in before), "Lab must be running normally")
        set_loads({1: 90, 2: 20, 3: 40})
        command = compose + [
            "--profile", "tools", "run", "-d", "-T",
            "--no-deps", "--pull", "never", "--name", name,
        ]
        filenames = () if args.use_image_code else (
            "xapp_live_steering.py", "xapp_mac_load.py",
            "xapp_radio_stats.py", "xapp_traffic_steering.py",
        )
        for filename in filenames:
            source = root / "test/xapp" / filename
            require(source.is_file(), f"Missing source: {source}")
            command += ["-v", f"{source}:/opt/oai-pi/test/xapp/{filename}:ro"]
        command += [
            "xapp-kpm", "xapp_live_steering.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ]
        created = True
        run(command, "start-xapp", 45)
        xapp_before = inspect([name], "xapp-before")[0]

        forward = wait_for(lambda rs: any(
            r["status"] == "recommendation"
            and (r.get("source"), r.get("target")) == ("cell-a", "cell-b")
            for r in rs), "forward recommendation")
        first = next(r for r in forward if r["status"] == "recommendation")
        wait_for(lambda rs: any(
            r["status"] == "cooldown" and r["time_s"] > first["time_s"]
            for r in rs), "forward cooldown")
        print("PASS: forward recommendation and cooldown", flush=True)

        boundary = rows()[-1]["time_s"]
        set_loads({1: 50, 2: 50})
        balanced = wait_for(lambda rs: sum(
            r["time_s"] > boundary and r["status"] == "balanced"
            and all(abs(value - 0.5) < 0.01 for value in r["cells"].values())
            for r in rs) >= 2, "balanced phase")
        print("PASS: balanced loads suppress recommendations", flush=True)

        boundary = balanced[-1]["time_s"]
        set_loads({1: 20, 2: 90})
        final = wait_for(lambda rs: any(
            r["time_s"] > boundary and r["status"] == "recommendation"
            and (r.get("source"), r.get("target")) == ("cell-b", "cell-a")
            for r in rs), "reverse recommendation")
        reverse = next(r for r in final if
                       r["time_s"] > boundary and r["status"] == "recommendation")
        require(reverse["time_s"] - first["time_s"] >= 30,
                "Recommendation cooldown was not respected")
        require(all(r["executed"] is False for r in final),
                "Unexpected executed action")
        require(any(r["time_s"] > boundary and r["status"] == "pending"
                    for r in final), "Missing reverse pending phase")
        require(identity(inspect([name], "xapp-after")[0]) == identity(xapp_before),
                "xApp process changed")
        summary["recommendations"] = [first, reverse]
        print("PASS: reverse recommendation, cooldown and unchanged xApp process",
              flush=True)

        run(docker + ["exec", name, "python3", "-c",
                      "from pathlib import Path; Path('/tmp/steering-stop').touch()"],
            "request-cleanup")
        require(run(docker + ["wait", name], "wait-xapp").strip() == "0",
                "Abnormal xApp exit")
        text = run(docker + ["logs", name], "final-xapp")
        require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 2,
                "Incomplete subscription cleanup")
        after = inspect(lab, "lab-after")
        require(all(item["State"]["Running"] and not item["State"]["Paused"]
                    for item in after), "Lab is not running normally")
        require({item["Name"]: identity(item) for item in before} ==
                {item["Name"]: identity(item) for item in after},
                "Lab processes changed")
        summary["passed"] = True
        print("PASS: normal cleanup and unchanged RIC/Agent processes", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        errors = []
        if created:
            try:
                item = inspect([name], "final-state")[0]
                if item["State"]["Running"]:
                    run(docker + ["exec", name, "python3", "-c",
                                  "from pathlib import Path; Path('/tmp/steering-stop').touch()"],
                        "final-cleanup")
                    run(docker + ["wait", name], "final-wait")
                run(docker + ["logs", "--timestamps", name], "evidence-xapp")
                run(docker + ["rm", name], "remove-xapp")
            except Exception as error:
                errors.append(str(error))
        for path, original in originals.items():
            try:
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(original)
                temporary.replace(path)
            except Exception as error:
                errors.append(str(error))
        summary["cleanup_errors"] = errors
        if errors:
            summary["passed"] = False
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {output}", flush=True)
        if errors:
            raise RuntimeError(f"Evidence/cleanup errors: {errors}")


if __name__ == "__main__":
    main()
