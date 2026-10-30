#!/usr/bin/env python3
"""Validate a real UE session against the patched AUSF through Compose."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "test/open5gs/.local"
COMPOSE = ROOT / "deploy/open5gs/compose.ausf-real-ue.json"
EXPECTED = "sha256:7ba6049f69cde00ba19eb19319020ea7d3d078b040bd0ecf122398f8fa96f3c4"
CORE = ["ausf", "udm", "udr", "nrf", "scp", "amf", "smf", "upf"]
DOCKER = ["sudo", "docker"]

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def call(args, timeout=30):
    return subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )

def output(args):
    result = call(args)
    result.check_returncode()
    return result.stdout

def snapshot():
    records = json.loads(output(["inspect", *CORE]))
    require(all(x["State"]["Running"] for x in records),
            "A core service is not running")
    return {
        x["Name"]: [x["Id"], x["Image"], x["State"]["Pid"],
                    x["State"]["StartedAt"], x["RestartCount"]]
        for x in records
    }

def main():
    require(COMPOSE.resolve().is_relative_to(ROOT), "Unexpected Compose path")
    config = json.loads(COMPOSE.read_text())
    project = "ausf-single-ue-" + uuid.uuid4().hex[:12]
    require(project.startswith("ausf-single-ue-"), "Unexpected project")
    require(set(config["services"]) == {"gnb", "nrue"}, "Unexpected services")
    require(json.loads(output(["inspect", "ausf"]))[0]["Image"] == EXPECTED,
            "Patched AUSF image is not active")
    before = snapshot()
    require(not output([
        "ps", "-a", "-q", "--filter",
        "label=com.docker.compose.project=" + project,
    ]).strip(), "Test project already has containers")
    network = json.loads(output([
        "network", "inspect", "docker_open5gs_default",
    ]))[0]
    occupied = {
        x.get("IPv4Address", "").split("/")[0]
        for x in network.get("Containers", {}).values()
    }
    require(not occupied.intersection({"172.22.0.160", "172.22.0.161"}),
            "Test addresses are occupied")

    (FIXTURE / "evidence").mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="real-ue-", dir=FIXTURE / "evidence"))
    dest.chmod(0o700)
    print("Evidence:", dest, flush=True)
    compose = ["compose", "-p", project, "-f", str(COMPOSE), "--profile", "ue"]
    summary = {
        "passed": False, "cleanup_errors": [],
        "scope": "Real single-UE session and TUN-bound UPF connectivity",
        "abnormal_recovery_validated": False,
    }
    touched = False
    try:
        touched = True
        result = call(compose + [
            "up", "-d", "--no-build", "--pull", "never", "gnb", "nrue",
        ], 90)
        (dest / "startup.log").write_text(result.stdout + result.stderr)
        result.check_returncode()
        ue = output(compose + ["ps", "-q", "nrue"]).strip()
        require(bool(ue), "UE container missing")
        deadline = time.monotonic() + 120
        address = None
        while time.monotonic() < deadline:
            state = json.loads(output(["inspect", ue]))[0]["State"]
            require(state["Running"], "UE exited before tunnel readiness")
            result = call([
                "exec", ue, "ip", "-4", "-j", "addr",
                "show", "dev", "oaitun_ue1",
            ])
            if result.returncode == 0:
                values = [
                    a["local"] for item in json.loads(result.stdout)
                    for a in item.get("addr_info", [])
                    if a.get("family") == "inet"
                ]
                if len(values) == 1:
                    address = values[0]
                    break
            time.sleep(2)
        require(address is not None, "UE tunnel readiness timeout")
        summary["ue_address"] = address
        for number in (1, 2):
            if number == 2:
                time.sleep(20)
            result = call([
                "exec", ue, "ping", "-n", "-I", "oaitun_ue1",
                "-c", "5", "-W", "2", "192.168.100.1",
            ], 25)
            (dest / f"ping-{number}.log").write_text(
                result.stdout + result.stderr)
            require(result.returncode == 0 and
                    ("5 received" in result.stdout or
                     "5 packets received" in result.stdout),
                    f"Ping round {number} failed")
        require(snapshot() == before, "Core service identity changed")
        summary["session_connectivity_passed"] = True
    except Exception as exc:
        summary["error"] = str(exc)
    finally:
        if touched:
            try:
                result = call(compose + ["logs", "--no-color", "--tail", "2000"])
                private = dest / "runtime-private.log"
                with private.open("x") as stream:
                    private.chmod(0o600)
                    stream.write(result.stdout + result.stderr)
            except Exception as exc:
                summary["diagnostic_error"] = str(exc)
            try:
                result = call(compose + ["down", "--timeout", "10"], 90)
                (dest / "cleanup.log").write_text(result.stdout + result.stderr)
                result.check_returncode()
                require(not output([
                    "ps", "-a", "-q", "--filter",
                    "label=com.docker.compose.project=" + project,
                ]).strip(), "Test containers remain")
            except Exception as exc:
                summary["cleanup_errors"].append(str(exc))
        try:
            require(snapshot() == before, "Core service identity changed")
        except Exception as exc:
            summary["baseline_error"] = str(exc)
        summary["passed"] = bool(
            summary.get("session_connectivity_passed")
            and not summary["cleanup_errors"]
            and "error" not in summary and "baseline_error" not in summary
        )
        with (dest / "summary.json").open("x") as stream:
            json.dump(summary, stream, indent=2)
            stream.write("\n")
        print(json.dumps(summary, indent=2), flush=True)
        print("Evidence retained:", dest, flush=True)
    return 0 if summary["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
