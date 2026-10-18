#!/usr/bin/env python3
"""Diagnose Style 4 subscription cleanup with the experimental UE stopped."""

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

DOCKER = ["sudo", "docker"]
NAMES = [
    "oai-pi-ocudu-zmq-lab-gnb-1",
    "oai-pi-ocudu-zmq-lab-nrue-1",
    "oai-pi-ocudu-zmq-lab-ric-1",
]


def run(args, timeout=20):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    result.check_returncode()
    return result.stdout


def states():
    values = json.loads(run(["inspect", *NAMES]))
    if (not values[0]["State"]["Running"]
            or values[1]["State"]["Running"]
            or not values[2]["State"]["Running"]):
        raise RuntimeError("Expected running gNB/RIC and stopped experimental UE")
    return {
        value["Name"].lstrip("/"): {
            "id": value["Id"], "image_id": value["Image"],
            "image": value["Config"]["Image"],
            "pid": value["State"]["Pid"],
            "started": value["State"]["StartedAt"],
            "restarts": value["RestartCount"],
            "cpuset": value["HostConfig"]["CpusetCpus"],
        } for value in values
    }


def ping(dest, label):
    text = run([
        "exec", NAMES[1], "ping", "-n", "-I", "oaitun_ue1",
        "-c", "5", "-W", "2", "192.168.100.1",
    ])
    (dest / f"ping-{label}.log").write_text(text)
    if "5 received" not in text and "5 packets received" not in text:
        raise RuntimeError(f"Ping {label} was not 5/5")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gnb-cpus", required=True)
    parser.add_argument("--ue-cpus", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output-dir", type=Path, default=
                        Path.home() / "Work/oai-test-evidence")
    parser.add_argument("--xapp-image", default=
        "limx59/oai-pi-ocudu-flexric-xapp:arm64-e2ap3-kpm3-node-id-fix")
    args = parser.parse_args()
    if not 10 <= args.seconds <= 300:
        parser.error("--seconds must be between 10 and 300")

    before = states()
    if (before[NAMES[0]]["cpuset"] != args.gnb_cpus
            or before[NAMES[1]]["cpuset"] != args.ue_cpus):
        raise RuntimeError("CPU assignment does not match requested experiment")

    root = Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix="ocudu-kpm-no-ue-subscription-", dir=args.output_dir.resolve()))
    demo = (root / "test/xapp/xapp_kpm.py").read_text()
    anchor = "            time.sleep(10)"
    if demo.count(anchor) != 1:
        raise RuntimeError("Unexpected demo duration anchor")
    demo = demo.replace(anchor, f"            time.sleep({args.seconds})", 1)
    compile(demo, "xapp_kpm.py", "exec")
    (dest / "xapp_kpm.py").write_text(demo)

    summary = {
        "mode": "no UE; subscription cleanup diagnostic only",
        "seconds": args.seconds, "before": before,
        "diagnostic_completed": False,
        "one_second_acceptance": "not evaluated by this diagnostic",
        "collection_errors": [], "cleanup_errors": [],
    }
    created = None
    process = None
    samples = []
    started = datetime.now(timezone.utc)
    print(f"Evidence: {dest}", flush=True)

    try:
        # UE connectivity is excluded from this diagnostic.
        created = run([
            "create", "--pull", "never", "--name", dest.name,
            "--network", "docker_open5gs_default", "--ulimit", "core=0",
            "--mount", f"type=bind,src={dest},dst=/evidence",
            "--mount", f"type=bind,src={dest}/xapp_kpm.py,"
            "dst=/opt/oai-pi/test/xapp/xapp_kpm.py,readonly",
            "--mount", f"type=bind,src={root}/deploy/ocudu/config/xapp.conf,"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "-e", "XAPP_OUTPUT=/evidence/kpm.csv",
            "--entrypoint", "timeout", args.xapp_image,
            "--signal=INT", "--kill-after=5s", f"{args.seconds + 30}s",
            "python3", "-u", "xapp_kpm_recorder.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ]).strip()

        with (dest / "recorder.stdout").open("w") as out, \
             (dest / "recorder.stderr").open("w") as err, \
             (dest / "cpu-samples.jsonl").open("w") as stream:
            process = subprocess.Popen(
                DOCKER + ["start", "-a", created],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            deadline = time.monotonic() + args.seconds + 45
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Recorder observation timeout")
                try:
                    sample = {
                        "at_utc": datetime.now(timezone.utc).isoformat(),
                        "containers": [
                            json.loads(line) for line in run([
                                "stats", "--no-stream", "--format", "{{json .}}",
                                *NAMES,
                            ], 10).splitlines() if line.strip()
                        ],
                    }
                    samples.append(sample)
                    stream.write(json.dumps(sample) + "\n")
                    stream.flush()
                except Exception as error:
                    summary["collection_errors"].append(f"CPU sample: {error}")
                time.sleep(2)

        state = json.loads(run(["inspect", created]))[0]["State"]
        summary["recorder_exit"] = state["ExitCode"]
        if state["Running"] or state["ExitCode"] != 0:
            raise RuntimeError(f"Recorder failed: exit={state['ExitCode']}")

        output = (dest / "recorder.stdout").read_text()
        errors = (dest / "recorder.stderr").read_text()
        if "SUBSCRIPTION DELETE RESPONSE rx" not in output:
            raise RuntimeError("Missing normal subscription delete response")
        if any(token in output + errors for token in (
            "CSV callback error", "Skipping mismatched",
            "Unsupported KPM format", "Traceback", "Assertion",
        )):
            raise RuntimeError("Recorder error; inspect saved logs")

        csv_path = dest / "kpm.csv"
        rows = []
        if csv_path.exists():
            with csv_path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
        if rows:
            raise RuntimeError("Unexpected UE measurement rows with the experimental UE stopped")
        if states() != before:
            raise RuntimeError("Experiment process identity changed")
        # No UE ping in this diagnostic.
        if states() != before:
            raise RuntimeError("Experiment process identity changed")

        summary.update({
            "csv_rows": len(rows),
            "diagnostic_completed": True,
            "subscription_delete_response_observed": True,
            "ue_connectivity": "not tested",
            "measurement_freshness": "not established",
        })
        print("Diagnostic completed: delete response received; no UE measurement rows.")
        print("One-second monitoring acceptance remains pending.", flush=True)
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        try:
            log = run([
                "logs", "--timestamps", "--tail", "2000",
                "--since", started.isoformat(), NAMES[0],
            ], 15)
            lines = [
                line for line in log.splitlines()
                if "[E2-" in line or "[E2SM-" in line
                or "UE Context Release" in line
            ]
            (dest / "gnb-filtered.log").write_text("\n".join(lines) + "\n")
            summary["ue_release_observed_in_collected_log"] = any(
                "UE Context Release" in line for line in lines)
        except Exception as error:
            summary["collection_errors"].append(f"gNB logs: {error}")
        try:
            if created:
                run(["rm", "-f", created])
            if process is not None and process.poll() is None:
                process.wait(timeout=10)
        except Exception as error:
            summary["cleanup_errors"].append(str(error))
        (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Evidence retained: {dest}", flush=True)
        if summary["cleanup_errors"] and "error" not in summary:
            raise RuntimeError(str(summary["cleanup_errors"]))


if __name__ == "__main__":
    main()
