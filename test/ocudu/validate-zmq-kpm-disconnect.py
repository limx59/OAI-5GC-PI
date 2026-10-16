#!/usr/bin/env python3
"""Exercise abrupt xApp disconnection within OCUDU KPM monitoring."""

import argparse
import csv
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location(
    "kpm", Path(__file__).with_name("validate-zmq-kpm.py"))
kpm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kpm)
run, require = kpm.run, kpm.require
DOCKER = kpm.DOCKER


def now():
    return datetime.now(timezone.utc)


def checked(directory, label, command, timeout=30):
    result = run(command, timeout)
    (directory / f"{label}.stdout").write_text(result.stdout)
    (directory / f"{label}.stderr").write_text(result.stderr)
    result.check_returncode()
    return result


def logs(name, since):
    result = run(DOCKER + [
        "logs", "--timestamps", "--since", since.isoformat(), name], 30)
    result.check_returncode()
    return result.stdout + result.stderr


def disconnect(directory, root, image):
    phase = directory / "disconnect"
    phase.mkdir()
    demo = (root / "test/xapp/xapp_kpm.py").read_text()
    anchor = "            time.sleep(10)"
    require(demo.count(anchor) == 1, "Unexpected demo duration anchor")
    demo = demo.replace(anchor, "            time.sleep(120)", 1)
    compile(demo, "xapp_kpm.py", "exec")
    demo_path = phase / "xapp_kpm.py"
    demo_path.write_text(demo)
    csv_path = phase / "kpm.csv"
    name = f"ocudu-kpm-{directory.parent.name}-{directory.name}-disconnect"
    created = None
    started = now()
    before_ric = kpm.ric_state()
    before_ran = kpm.base.states()
    before_ip = kpm.base.address()
    result_data = {"passed": False}
    cleanup_errors = []

    try:
        result = checked(phase, "create", DOCKER + [
            "create", "--pull", "never", "--name", name,
            "--network", "docker_open5gs_default", "--ulimit", "core=0",
            "--mount",
            f"type=bind,src={root}/deploy/ocudu/config/xapp.conf,"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "--mount", f"type=bind,src={phase},dst=/evidence",
            "--mount", f"type=bind,src={demo_path},"
            "dst=/opt/oai-pi/test/xapp/xapp_kpm.py,readonly",
            "-e", "XAPP_OUTPUT=/evidence/kpm.csv",
            "--entrypoint", "timeout", image,
            "--signal=INT", "--kill-after=5s", "150s",
            "python3", "-u", "xapp_kpm_recorder.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ])
        created = result.stdout.strip()
        checked(phase, "start", DOCKER + ["start", created])
        deadline = time.monotonic() + 35
        rows = []
        while True:
            kpm.ric_state()
            state = checked(
                phase, "readiness-state", DOCKER + ["inspect", created])
            require(json.loads(state.stdout)[0]["State"]["Running"],
                    "xApp stopped before fault injection")
            if csv_path.exists():
                with csv_path.open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
            stamps = {row.get("received_at_utc") for row in rows}
            if len(stamps) >= 2:
                break
            require(time.monotonic() < deadline,
                    "Timed out waiting for two active KPM reports")
            time.sleep(0.5)

        before_output = logs(created, started)
        (phase / "xapp-before-kill.log").write_text(before_output)
        require("Subscribed: node=420" in before_output,
                "Expected node subscription not observed")
        require("SUBSCRIPTION_DELETE_REQUEST" not in before_output,
                "Subscription already deleting before fault")
        require(not any(token in before_output for token in (
            "CSV callback error", "Traceback", "Assertion")),
            "xApp error before fault injection")

        killed = now()
        checked(phase, "kill", DOCKER + ["kill", "--signal=KILL", created])
        state = checked(phase, "killed-state", DOCKER + ["inspect", created])
        state = json.loads(state.stdout)[0]["State"]
        require(not state["Running"] and state["ExitCode"] == 137,
                f"Unexpected killed xApp state: {state}")

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(kpm.ric_state() == before_ric,
                    "RIC stopped or changed identity after xApp disconnection")
            require(kpm.base.states() == before_ran,
                    "RAN process identity changed after fault")
            time.sleep(0.5)

        gnb_output = logs(kpm.NAMES[0], killed)
        lines = [
            line for line in gnb_output.splitlines()
            if re.search(r"\[E2[^]]*\]", line)
            and not kpm.base.SENSITIVE.search(line)
        ]
        (phase / "gnb-e2.log").write_text("\n".join(lines) + "\n")
        responses, sends = [], []
        for line in lines:
            if ("Sending subscription delete response" not in line
                    and "Sending E2 indication" not in line):
                continue
            stamp = datetime.fromisoformat(
                line.split()[0].replace("Z", "+00:00"))
            if "Sending subscription delete response" in line:
                responses.append(stamp)
            if "Sending E2 indication" in line:
                sends.append(stamp)
        require(len(responses) == 1,
                "Expected one automatic gNB subscription delete response")
        require(not any((stamp - responses[0]).total_seconds() > 1
                        for stamp in sends),
                "gNB continued indications beyond deletion grace period")
        observed = now()
        require((observed - responses[0]).total_seconds() >= 5,
                "Insufficient observation after automatic deletion")
        require(kpm.base.address() == before_ip, "UE address changed")

        ric_output = logs(kpm.RIC, killed)
        (phase / "ric.log").write_text(ric_output)
        require("disconnected!" in ric_output,
                "RIC did not record xApp disconnection")
        require("Automatically removing pending" in ric_output,
                "Automatic subscription cleanup not observed")
        require(not any(token in ric_output for token in (
            "Assertion", "Aborted", "Segmentation fault")),
            "RIC failure observed")
        result_data.update({
            "passed": True,
            "reports_before_kill": len(stamps),
            "csv_rows_before_kill": len(rows),
            "xapp_exit_code": state["ExitCode"],
            "killed_utc": killed.isoformat(),
            "gnb_delete_response_utc": responses[0].isoformat(),
            "observed_until_utc": observed.isoformat(),
            "ric_identity_unchanged": True,
            "ran_identity_unchanged": True,
            "ue_address_unchanged": True,
        })
    except Exception as error:
        result_data["error"] = str(error)
        raise
    finally:
        if created:
            try:
                checked(phase, "remove", DOCKER + ["rm", "-f", created])
            except Exception as error:
                cleanup_errors.append(str(error))
        try:
            (phase / "ric-final.log").write_text(logs(kpm.RIC, started))
        except Exception as error:
            cleanup_errors.append(str(error))
        result_data["cleanup_errors"] = cleanup_errors
        if cleanup_errors:
            result_data["passed"] = False
        (phase / "summary.json").write_text(
            json.dumps(result_data, indent=2) + "\n")
        require(not cleanup_errors, str(cleanup_errors))

    print("PASS: abrupt xApp exit; RIC survived; automatic subscription "
          "deletion and observation guard passed", flush=True)
    return result_data


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ric-image", required=True)
    args, remaining = parser.parse_known_args()
    DOCKER[:] = [
        "sudo", "env", f"OCUDU_RIC_IMAGE={args.ric_image}", "docker"]
    result = run(DOCKER + ["inspect", kpm.RIC])
    result.check_returncode()
    require(json.loads(result.stdout)[0]["Config"]["Image"] == args.ric_image,
            "Running RIC image does not match --ric-image")

    original = kpm.record_during

    def record(directory, direction, traffic_cmd, root, image):
        fault = None
        if direction == "uplink":
            fault = disconnect(directory, root, image)
        traffic, details = original(
            directory, direction, traffic_cmd, root, image)
        if fault is not None:
            details["preceding_disconnect"] = fault
        return traffic, details

    kpm.record_during = record
    sys.argv = [sys.argv[0]] + remaining
    kpm.main()


if __name__ == "__main__":
    main()
