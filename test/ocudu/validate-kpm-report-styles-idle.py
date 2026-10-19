#!/usr/bin/env python3
"""Validate Style 1/4 idle responses without generating recording-time traffic."""

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
    if not all(value["State"]["Running"] for value in values):
        raise RuntimeError("An experiment container stopped")
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
    parser.add_argument("--style", type=int, choices=(1, 4), required=True)
    parser.add_argument("--gnb-cpus", required=True)
    parser.add_argument("--ue-cpus", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output-dir", type=Path, default=
                        Path.home() / "Work/oai-test-evidence")
    parser.add_argument("--xapp-image", default=
        "limx59/oai-pi-ocudu-flexric-xapp:arm64-kpm-styles-test")
    args = parser.parse_args()
    expected_format = "1" if args.style == 1 else "3"
    if not 10 <= args.seconds <= 300:
        parser.error("--seconds must be between 10 and 300")

    before = states()
    if (before[NAMES[0]]["cpuset"] != args.gnb_cpus
            or before[NAMES[1]]["cpuset"] != args.ue_cpus):
        raise RuntimeError("CPU assignment does not match requested experiment")

    root = Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix=f"ocudu-kpm-style{args.style}-idle-", dir=args.output_dir.resolve()))
    demo = (root / "test/xapp/xapp_kpm.py").read_text()
    anchor = "            time.sleep(10)"
    if demo.count(anchor) != 1:
        raise RuntimeError("Unexpected demo duration anchor")
    demo = demo.replace(anchor, f"            time.sleep({args.seconds})", 1)
    compile(demo, "xapp_kpm.py", "exec")
    (dest / "xapp_kpm.py").write_text(demo)

    summary = {
        "mode": "idle; no traffic generated during recording",
        "seconds": args.seconds, "before": before,
        "style": args.style,
        "expected_indication_format": expected_format,
        "xapp_image": args.xapp_image,
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
        ping(dest, "before")
        created = run([
            "create", "--pull", "never", "--name", dest.name,
            "--network", "docker_open5gs_default", "--ulimit", "core=0",
            "--mount", f"type=bind,src={dest},dst=/evidence",
            "--mount", f"type=bind,src={dest}/xapp_kpm.py,"
            "dst=/opt/oai-pi/test/xapp/xapp_kpm.py,readonly",
            "--mount", f"type=bind,src={root}/deploy/ocudu/config/xapp.conf,"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "-e", f"OAI_PI_KPM_REPORT_STYLE={args.style}",
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
        if f"selected KPM action format = {args.style}" not in output:
            raise RuntimeError("Missing SDK action-format marker")
        if "SUBSCRIPTION DELETE RESPONSE rx" not in output:
            raise RuntimeError("Missing normal subscription delete response")
        if any(token in output + errors for token in (
            "CSV callback error", "Skipping mismatched",
            "Unsupported KPM format", "Traceback", "Assertion",
        )):
            raise RuntimeError("Recorder error; inspect saved logs")

        with (dest / "kpm.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        expected = {"DRB.UEThpDl", "DRB.UEThpUl"}
        if {row["measurement"] for row in rows} != expected:
            raise RuntimeError("Missing or unexpected measurements")
        for row in rows:
            if (row["node_id"] != "420" or row["incomplete"] != "0"
                    or row["indication_format"] != expected_format
                    or row["value_type"] not in ("integer", "real")
                    or not math.isfinite(float(row["value"]))
                    or float(row["value"]) < 0
                    or (row["mcc"], row["mnc"], row["ran_type"]) != ("1", "1", "7")):
                raise RuntimeError("Invalid measurement row")

        stamps = sorted({
            datetime.fromisoformat(row["received_at_utc"]) for row in rows
        })
        if any(stamp.utcoffset() is None for stamp in stamps):
            raise RuntimeError("Receive timestamp lacks timezone")
        gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
        grouped = {}
        for row in rows:
            key = (row["received_at_utc"], row["ue_report_index"],
                   row["row_index"])
            values = grouped.setdefault(key, {})
            if row["measurement"] in values:
                raise RuntimeError("Duplicate metric within a report row")
            values[row["measurement"]] = float(row["value"])
        if any(set(values) != expected for values in grouped.values()):
            raise RuntimeError("Missing paired DL/UL measurements")
        zero_reports = sum(
            all(value == 0 for value in values.values())
            for values in grouped.values()
        )
        summary["paired_zero_throughput_reports"] = zero_reports
        if zero_reports < 5:
            raise RuntimeError("Expected at least five paired zero-throughput reports")
        if len(stamps) < max(5, args.seconds // 2):
            raise RuntimeError("Insufficient idle reports")
        if not gaps:
            raise RuntimeError("Insufficient KPM timestamps")
        if states() != before:
            raise RuntimeError("Experiment process identity changed")
        ping(dest, "after")
        if states() != before:
            raise RuntimeError("Experiment process identity changed")

        summary.update({
            "csv_rows": len(rows), "receive_timestamps": len(stamps),
            "receive_gaps_seconds": gaps,
            "gap_min": min(gaps), "gap_median": statistics.median(gaps),
            "gap_max": max(gaps), "diagnostic_completed": True,
        })
        print(f"CSV rows={len(rows)}, reports={len(stamps)}", flush=True)
        print("Receive gaps: min={:.3f}s median={:.3f}s max={:.3f}s".format(
            min(gaps), statistics.median(gaps), max(gaps)), flush=True)
        for name in NAMES:
            values = [
                float(item["CPUPerc"].rstrip("%"))
                for sample in samples for item in sample["containers"]
                if item.get("Name") == name
            ]
            if values:
                print(f"{name}: CPU median={statistics.median(values):.1f}% "
                      f"max={max(values):.1f}%", flush=True)
        print(f"PASS: Style {args.style}; idle report format, numeric records, "
              f"{zero_reports} paired zero-throughput reports and delete response.",
              flush=True)
        print("Cadence statistics only; post-delete silence not checked here.", flush=True)
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
