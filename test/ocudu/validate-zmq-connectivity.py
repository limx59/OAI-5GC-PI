#!/usr/bin/env python3
"""Validate OCUDU/OAI ZMQ session establishment and TUN-bound UPF pings."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

NAMES = ["oai-pi-ocudu-zmq-lab-gnb-1", "oai-pi-ocudu-zmq-lab-nrue-1"]
DOCKER = ["sudo", "docker"]
SENSITIVE = re.compile(
    r"IMSI|IMEI|UICC|(?:\bKi\b|\bOPc\b|\bkey\b)\s*[:=]", re.I)

def run(cmd, timeout=20):
    return subprocess.run(cmd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=timeout)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def states():
    r = run(DOCKER + ["inspect", *NAMES])
    r.check_returncode()
    records = json.loads(r.stdout)
    require(all(i["State"]["Running"] for i in records), "Process stopped")
    return {i["Name"].lstrip("/"): [
        i["Id"], i["Image"], i["State"]["Pid"],
        i["State"]["StartedAt"], i["RestartCount"],
    ] for i in records}

def address():
    r = run(DOCKER + ["exec", NAMES[1], "ip", "-4", "-j",
                      "addr", "show", "dev", "oaitun_ue1"])
    if r.returncode:
        return None
    values = [a["local"] for interface in json.loads(r.stdout)
              for a in interface.get("addr_info", [])
              if a.get("family") == "inet"]
    return values[0] if len(values) == 1 else None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/ocudu-zmq-connectivity"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    deploy = root / "deploy/ocudu"
    compose = DOCKER + ["compose", "-f", str(deploy / "compose.zmq.yaml"),
                       "-f", str(deploy / "compose.zmq-worker-test.yaml"),
                       "--profile", "ue"]
    # Refuse to interrupt an already-running experiment.
    for name in NAMES:
        r = run(DOCKER + ["container", "ls", "--filter",
                          f"name=^/{name}$", "--format", "{{.Names}}"])
        r.check_returncode()
        require(not r.stdout.strip(), f"Experiment already running: {name}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    summary = {"passed": False, "rounds": [],
               "scope": "ZMQ session, TUN-bound UPF pings, bounded stability"}
    print(f"Evidence: {output}", flush=True)
    try:
        for number in range(1, args.rounds + 1):
            directory = output / f"round-{number}"
            directory.mkdir()
            item = {"number": number, "passed": False, "cleanup_errors": []}
            summary["rounds"].append(item)
            baseline = None
            print(f"Running round {number}/{args.rounds}", flush=True)
            try:
                r = run(compose + ["up", "-d", "--force-recreate",
                                   "--no-build", "--pull", "never",
                                   "gnb", "nrue"], 60)
                (directory / "startup.log").write_text(r.stdout + r.stderr)
                r.check_returncode()
                baseline = states()
                item["before"] = baseline
                deadline = time.monotonic() + 60
                ip = address()
                while not ip:
                    states()
                    require(time.monotonic() < deadline, "UE address timeout")
                    time.sleep(1)
                    ip = address()
                item["ue_ip"] = ip

                for label in ("before", "after"):
                    if label == "after":
                        time.sleep(20)
                    require(states() == baseline, "Process identity changed")
                    require(address() == ip, "UE address changed")
                    r = run(DOCKER + ["exec", NAMES[1], "ping", "-n",
                                      "-I", "oaitun_ue1", "-c", "5",
                                      "-W", "2", "192.168.100.1"], 20)
                    text = r.stdout + r.stderr
                    (directory / f"ping-{label}.log").write_text(text)
                    require(r.returncode == 0 and
                            re.search(r"5 (?:packets )?received", text),
                            f"Ping {label}: expected 5/5 replies")
                item["checks_passed"] = True
            except Exception as exc:
                item["error"] = str(exc)
                raise
            finally:
                for name in NAMES:
                    try:
                        since = baseline[name][3] if baseline else None
                        cmd = DOCKER + ["logs", "--timestamps"]
                        if since:
                            cmd += ["--since", since]
                        r = run(cmd + [name], 30)
                        r.check_returncode()
                        lines = [s for s in (r.stdout + r.stderr).splitlines()
                                 if not SENSITIVE.search(s)]
                        (directory / f"{name}.log").write_text(
                            "\n".join(lines) + "\n")
                    except Exception as exc:
                        item["cleanup_errors"].append(f"Log capture: {exc}")
                try:
                    r = run(compose + ["stop", "nrue", "gnb"], 45)
                    (directory / "cleanup.log").write_text(r.stdout + r.stderr)
                    r.check_returncode()
                    r = run(DOCKER + ["inspect", *NAMES])
                    r.check_returncode()
                    require(all(not i["State"]["Running"]
                                for i in json.loads(r.stdout)),
                            "Experiment still running")
                except Exception as exc:
                    item["cleanup_errors"].append(str(exc))
            require(not item["cleanup_errors"], str(item["cleanup_errors"]))
            item["passed"] = True
            print(f"PASS: round {number}, IP={ip}, both pings 5/5, cleanup",
                  flush=True)
        summary["passed"] = True
    except Exception as exc:
        summary["error"] = str(exc)
        raise
    finally:
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)
    print("PASS: all requested connectivity rounds.", flush=True)

if __name__ == "__main__":
    main()
