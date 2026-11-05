#!/usr/bin/env python3
"""Retain a bounded single-UE ZMQ session with periodic UPF probes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ["docker"] if os.environ.get("OCUDU_CONTAINER_RUNNER") == "1" else ["sudo", "docker"]
IMAGES = {
    "gnb": "limx59/oai-pi-ocudu-gnb:arm64-steering-prb-kpm-metadata-v2-test",
    "nrue": "limx59/oai-pi-oai-nr-ue:arm64-zmq-dci10-config-selection-test",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def invoke(args, timeout=30, check=True):
    value = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    require(not check or value.returncode == 0,
            "Docker operation failed: " + (value.stdout + value.stderr)[-2000:])
    return value


def output(args, timeout=30):
    return invoke(args, timeout).stdout.strip()


def identity(cid):
    item = json.loads(output(["inspect", cid]))[0]
    state = item["State"]
    return {
        "id": item["Id"], "image": item["Image"],
        "pid": state["Pid"], "started": state["StartedAt"],
        "restarts": item["RestartCount"], "running": state["Running"],
        "oom_killed": state["OOMKilled"],
    }


def address(cid):
    result = invoke([
        "exec", cid, "ip", "-4", "-j", "addr", "show", "dev", "oaitun_ue1",
    ], timeout=10, check=False)
    if result.returncode:
        return None
    values = [
        item["local"] for interface in json.loads(result.stdout)
        for item in interface.get("addr_info", [])
        if item.get("family") == "inet"
    ]
    return values[0] if len(values) == 1 else None


def save(path, value):
    with path.open("x") as stream:
        path.chmod(0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--interval-seconds", type=int, default=30)
    args = parser.parse_args()
    require(60 <= args.duration_seconds <= 86400, "Duration must be 60..86400 seconds")
    require(15 <= args.interval_seconds <= 60, "Interval must be 15..60 seconds")
    parent = ROOT / "test/ocudu/.local/evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-session-stability-", dir=parent))
    dest.chmod(0o700)
    project = "ocudu-session-" + uuid.uuid4().hex[:12]
    report = {
        "passed": False, "error": None, "cleanup_errors": [],
        "scope": "Bounded single-UE session with periodic TUN-bound UPF probes",
        "requested_duration_s": args.duration_seconds,
        "probe_interval_s": args.interval_seconds,
        "continuous_user_traffic_validated": False,
        "unobserved_between_probe_state_changes_excluded": False,
        "samples": [],
    }
    compose = []
    containers = {}
    baseline = {}
    touched = False
    old_umask = os.umask(0o077)
    print("Evidence:", dest, flush=True)
    try:
        ids = output(["ps", "-q", "--no-trunc"]).split()
        require(ids, "No running baseline containers")
        baseline = {cid: identity(cid) for cid in ids}
        report["baseline_before"] = baseline
        network = json.loads(output([
            "network", "inspect", "docker_open5gs_default",
        ]))[0]
        for endpoint in network.get("Containers", {}).values():
            require(endpoint.get("IPv4Address", "").split("/")[0]
                    not in ("172.22.0.160", "172.22.0.161"),
                    "Laboratory address occupied")
        report["images"] = {}
        for name, reference in IMAGES.items():
            item = json.loads(output(["image", "inspect", reference]))[0]
            require(item["Os"] == "linux" and item["Architecture"] == "arm64",
                    "Unexpected image platform")
            report["images"][name] = {"reference": reference, "id": item["Id"]}
        prepare = runpy.run_path(str(
            ROOT / "test/ocudu/prepare-session-stability.py"
        ))["prepare"]
        report["configuration"] = prepare(ROOT, dest / "config")
        config = dest / "config/gnb.yml"
        env = dest / "compose.env"
        env.write_text(f"OCUDU_SESSION_CONFIG={config}\n")
        compose = [
            "compose", "--project-name", project, "--env-file", str(env),
            "-f", str(ROOT / "deploy/ocudu/compose.zmq.yaml"),
            "-f", str(ROOT / "deploy/ocudu/compose.session-stability.yaml"),
            "--profile", "ue",
        ]
        resolved = json.loads(output(compose + ["config", "--format", "json"]))
        require(set(resolved["services"]) == set(IMAGES), "Unexpected services")
        inputs = {config}
        for name, reference in IMAGES.items():
            service = resolved["services"][name]
            require(service["image"] == reference
                    and service.get("pull_policy") == "never"
                    and not service.get("ports")
                    and not service.get("container_name")
                    and service.get("restart") == "no",
                    "Unexpected service configuration: " + name)
            for mount in service.get("volumes", []):
                require(mount["type"] == "bind"
                        and mount.get("read_only") is True,
                        "Unexpected configuration mount")
                path = Path(mount["source"]).resolve()
                require(path.is_file(), "Missing mounted input")
                inputs.add(path)
            if name == "gnb":
                matches = [m for m in service["volumes"]
                           if m["target"] == "/etc/ocudu/gnb.yml"]
                require(len(matches) == 1
                        and Path(matches[0]["source"]).resolve() == config,
                        "Private gNB configuration not selected")
        report["input_hashes"] = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in inputs
        }
        save(dest / "resolved-compose.json", resolved)
        touched = True
        startup = invoke(compose + [
            "up", "-d", "--no-build", "--pull", "never", "gnb", "nrue",
        ], timeout=60, check=False)
        (dest / "startup.log").write_text(startup.stdout + startup.stderr)
        require(startup.returncode == 0, "Compose startup failed")
        for name in IMAGES:
            cid = output(compose + ["ps", "--all", "-q", name])
            require(cid and len(cid.splitlines()) == 1, "Missing test container")
            containers[name] = cid
        before = {name: identity(cid) for name, cid in containers.items()}
        report["test_before"] = before
        for name, value in before.items():
            require(value["running"] and not value["oom_killed"]
                    and value["restarts"] == 0
                    and value["image"] == report["images"][name]["id"],
                    "Unexpected initial process: " + name)

        def check():
            require({name: identity(cid) for name, cid in containers.items()}
                    == before, "Test process identity changed")
            require({cid: identity(cid) for cid in baseline} == baseline,
                    "Baseline process identity changed")

        deadline = time.monotonic() + 90
        while True:
            check()
            ue_address = address(containers["nrue"])
            if ue_address:
                break
            require(time.monotonic() < deadline, "UE tunnel readiness timeout")
            time.sleep(1)
        report["ue_address"] = ue_address
        started = time.monotonic()
        report["observation_started_monotonic_s"] = started
        next_probe = started
        with (dest / "samples.jsonl").open("x") as stream:
            while True:
                while time.monotonic() < next_probe:
                    time.sleep(min(1, max(0, next_probe - time.monotonic())))
                check()
                require(address(containers["nrue"]) == ue_address,
                        "UE tunnel address changed")
                number = len(report["samples"]) + 1
                sent = time.monotonic()
                ping = invoke([
                    "exec", containers["nrue"], "ping", "-n",
                    "-I", "oaitun_ue1", "-c", "5", "-W", "2",
                    "192.168.100.1",
                ], timeout=20, check=False)
                text = ping.stdout + ping.stderr
                (dest / f"ping.{number:06d}.log").write_text(text)
                received = time.monotonic()
                good = bool(
                    ping.returncode == 0
                    and re.search(r"5 packets transmitted,\s*5 (?:packets )?received", text)
                    and re.search(r"(?:^|,\s)0% packet loss", text)
                )
                sample = {
                    "sequence": number, "started_s": sent,
                    "finished_s": received, "elapsed_s": received - started,
                    "ue_address": ue_address, "ping_returncode": ping.returncode,
                    "ping_passed": good,
                }
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                report["samples"].append(sample)
                require(good, "Expected five UPF ping replies")
                check()
                print(f"PASS: probe {number}, elapsed={received - started:.1f}s",
                      flush=True)
                if sent - started >= args.duration_seconds:
                    break
                next_probe = min(sent + args.interval_seconds,
                                 started + args.duration_seconds)
        report["observed_duration_s"] = time.monotonic() - started
        report["test_after"] = {name: identity(cid) for name, cid in containers.items()}
        for path, digest in report["input_hashes"].items():
            require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest,
                    "Mounted input changed")
        source = ROOT / report["configuration"]["source"]
        require(hashlib.sha256(source.read_bytes()).hexdigest()
                == report["configuration"]["source_sha256"],
                "Base configuration changed")
        report["checks_passed"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        for name, cid in containers.items():
            try:
                with (dest / f"{name}.final.log").open("x") as stream:
                    result = subprocess.run(
                        DOCKER + ["logs", "--timestamps", cid],
                        stdout=stream, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, timeout=60,
                    )
                require(result.returncode == 0, "Log collection failed: " + name)
            except Exception as error:
                report["cleanup_errors"].append(str(error))
        if touched:
            try:
                result = invoke(compose + ["down", "--timeout", "15"], timeout=60)
                (dest / "cleanup.log").write_text(result.stdout + result.stderr)
                require(not output([
                    "ps", "-aq", "--filter",
                    "label=com.docker.compose.project=" + project,
                ]), "Test containers remain")
            except Exception as error:
                report["cleanup_errors"].append(str(error))
        if baseline:
            try:
                report["baseline_after"] = {
                    cid: identity(cid) for cid in baseline
                }
                require(report["baseline_after"] == baseline,
                        "Baseline changed")
            except Exception as error:
                report["cleanup_errors"].append(str(error))
        report["passed"] = bool(report.get("checks_passed")
                                and not report["cleanup_errors"])
        save(dest / "summary.json", report)
        os.umask(old_umask)
        print(json.dumps({
            key: report.get(key) for key in (
                "passed", "error", "cleanup_errors", "observed_duration_s",
                "ue_address",
            )
        }, indent=2), flush=True)
        print("Evidence:", dest, flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
