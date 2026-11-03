#!/usr/bin/env python3
"""Collect online UL load and grant evidence around slice updates."""
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ["sudo", "docker"]
CLIENT = "limx59/oai-pi-ocudu-slice-control-client:arm64-rrm-policy-ratio-ws-client-test@sha256:6b9a231faec61a643b68582ae69701ce3e8da2e14ea62b829cc6325c27efb40e"
CHECKER = "limx59/oai-pi-ocudu-config-check:arm64-slicing-test@sha256:2e750f07d68d00cdf2bdc34c9bfc28f2928e70ea393cbf17b137d218dc063186"
CLIENT_ID = "sha256:6b9a231faec61a643b68582ae69701ce3e8da2e14ea62b829cc6325c27efb40e"
CHECKER_ID = "sha256:2e750f07d68d00cdf2bdc34c9bfc28f2928e70ea393cbf17b137d218dc063186"
IMAGE_IDS = {
    "gnb": "sha256:8bceed7d42bccddd286a7c6d29e662f0daf788e4c5dc73b8a2ba9b4fb279724b",
    "nrue": "sha256:bbdceed41714844717eaf9a06e09284f5404e27daff870d1f1ec08c782182047",
}


IMAGE_IDS["traffic"] = 'sha256:6146f02626b1a5157552ed9be9afdfc92a2746fb5c33b38051c8aa80172a9904'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def progress(message):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
          + " " + message, flush=True)


def invoke(args, timeout=30, check=True):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        timeout=timeout, stdin=subprocess.DEVNULL,
    )
    if check and result.returncode:
        raise RuntimeError(
            "Docker command failed: " + " ".join(args[:3])
            + "\n" + (result.stdout + result.stderr)[-2000:]
        )
    return result


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


def snapshot(ids):
    return {cid: identity(cid) for cid in ids}


def logs(cid):
    result = invoke(["logs", cid])
    return result.stdout + result.stderr


def image(reference, expected):
    item = json.loads(output(["image", "inspect", reference]))[0]
    require(item["Id"] == expected
            and item["Os"] == "linux"
            and item["Architecture"] == "arm64",
            "Unexpected image: " + reference)
    return item["Id"]


def main():
    parent = ROOT / "test/ocudu/.local/evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-slice-online-ul-drain-", dir=parent))
    dest.chmod(0o700)
    progress("Evidence: " + str(dest))
    project = "ocudu-slice-ul-drain-" + uuid.uuid4().hex[:12]
    summary = {
        "passed": False,
        "scope": "Single-UE timed UDP UL with server grace and bounded receive drain",
        "transport": "UDP",
        "server_grace_seconds": 180,
        "control_requests_attempted": 0,
        "control_requests_sent": 0,
        "raw_grant_limits_validated": False,
        "ul_cap_effect_validated": False,
        "ul_load": [],
        "multi_agent_control_validated": False,
        "phases": [], "cleanup_errors": [],
    }
    auxiliary = []
    containers = {}
    compose = []
    touched = False
    baseline = None
    baseline_ids = []

    def temporary_container(args):
        cid = output([
            "create", "--name", project + "-aux-" + uuid.uuid4().hex[:8],
            "--label", "ocudu.slice.test=" + project,
            "--ulimit", "core=0",
        ] + args)
        auxiliary.append(cid)
        return cid

    def check_processes():
        for name, cid in containers.items():
            require(identity(cid) == summary["test_before"][name],
                    "Test process identity changed: " + name)

    def ping(label):
        result = invoke([
            "exec", containers["nrue"], "ping", "-n",
            "-I", "oaitun_ue1", "-c", "5", "-W", "2", "192.168.100.1",
        ], timeout=20, check=False)
        text = result.stdout + result.stderr
        (dest / ("ping-" + label + ".log")).write_text(text)
        require(result.returncode == 0
                and re.search(r"5 packets transmitted,\s*5 (?:packets )?received", text)
                and re.search(r"(?:^|,\s)0% packet loss", text),
                "Expected five UPF ping replies: " + label)


    def ul_load(label):
        check_processes()
        progress("UL load " + label + ": 10 Mbit/s UDP for 6 seconds")
        (dest / ("gnb.ul-" + label + ".before-load.log")).write_text(
            logs(containers["gnb"])
        )
        before_result = invoke(["logs", containers["traffic"]])
        server_before_streams = {
            "stdout": before_result.stdout, "stderr": before_result.stderr,
        }
        (dest / f"traffic.{label}.before-load.streams.json").write_text(
            json.dumps(server_before_streams, indent=2) + "\n"
        )
        server_before = before_result.stdout + before_result.stderr
        (dest / f"traffic.{label}.before-load.log").write_text(server_before)
        result = invoke([
            "exec", containers["nrue"],
            "timeout", "--signal=TERM", "--kill-after=3s", "240s",
            "iperf3", "-c", "172.22.0.151", "-p", "5201",
            "-B", summary["ue_address"],
            "-u", "-b", "10M", "-l", "1200", "-t", "6",
            "-J", "--get-server-output",
        ], timeout=250, check=False)
        (dest / ("iperf-ul-" + label + ".json")).write_text(result.stdout)
        (dest / ("iperf-ul-" + label + ".stderr.log")).write_text(result.stderr)
        require(result.returncode == 0,
                "UL iperf3 process failed: " + label)
        data = json.loads(result.stdout)
        require("error" not in data, "UL iperf3 error: " + label)
        connected = data.get("start", {}).get("connected", [])
        require(len(connected) == 1
                and connected[0].get("local_host") == summary["ue_address"]
                and connected[0].get("remote_host") == "172.22.0.151",
                "Unexpected UL traffic connection")
        server = data.get("server_output_json")
        require(isinstance(server, dict) and "error" not in server,
                "UL server JSON missing or invalid")
        receiver = server.get("end", {}).get("sum_received")
        if receiver is None:
            receiver = server.get("end", {}).get("sum")
        require(isinstance(receiver, dict)
                and receiver.get("sender") is not True
                and receiver.get("bytes", 0) >= 65536
                and receiver.get("bits_per_second", 0) > 0,
                "Insufficient server-confirmed UL traffic")
        parameters = data.get("start", {}).get("test_start", {})
        require(parameters.get("protocol") == "UDP"
                and parameters.get("duration") == 6
                and parameters.get("target_bitrate") == 10000000
                and parameters.get("blksize") == 1200,
                "Unexpected timed UDP parameters")
        sent = data.get("end", {}).get("sum_sent", {})
        client_received = data.get("end", {}).get("sum_received", {})
        require(sent.get("bytes") == receiver["bytes"]
                and client_received.get("bytes") == receiver["bytes"]
                and receiver.get("lost_packets") == 0,
                "UDP final byte counts or packet loss require review")
        after_result = invoke(["logs", containers["traffic"]])
        server_after_streams = {
            "stdout": after_result.stdout, "stderr": after_result.stderr,
        }
        (dest / f"traffic.{label}.after-load.streams.json").write_text(
            json.dumps(server_after_streams, indent=2) + "\n"
        )
        server_after = after_result.stdout + after_result.stderr
        (dest / f"traffic.{label}.after-load.log").write_text(server_after)
        require(all(
            server_after_streams[key].startswith(server_before_streams[key])
            for key in ("stdout", "stderr")
        ), "Traffic stream log history changed")
        server_delta = "\n".join(
            server_after_streams[key][len(server_before_streams[key]):]
            for key in ("stdout", "stderr")
        )
        require(server_delta.count(
                    "LAB_IPERF_SERVER_GRACE seconds=180") == 1,
                "Server grace activation missing or duplicated")
        drain = re.findall(
            r"LAB_IPERF_UDP_DRAIN before=(\d+) after=(\d+) "
            r"polls=(\d+) quiet_reached=(\d+)",
            server_delta,
        )
        require(len(drain) == 1,
                "UDP drain marker missing or duplicated")
        drain_before, drain_after, drain_polls, drain_quiet = map(int, drain[0])
        require(drain_after >= drain_before
                and 50 <= drain_polls <= 500
                and drain_quiet == 1,
                "UDP receive drain did not reach a quiet interval")
        time.sleep(1)
        check_processes()
        (dest / ("gnb.ul-" + label + ".after-load.log")).write_text(
            logs(containers["gnb"])
        )
        summary["ul_load"].append({
            "phase": label,
            "offered_bits_per_second": 10000000,
            "requested_seconds": 6,
            "drain_bytes_before": drain_before,
            "drain_bytes_after": drain_after,
            "drain_polls": drain_polls,
            "drain_quiet_reached": bool(drain_quiet),
            "receiver_bytes": receiver["bytes"],
            "receiver_bits_per_second": receiver["bits_per_second"],
            "receiver_packets": receiver.get("packets"),
            "receiver_lost_packets": receiver.get("lost_packets"),
            "receiver_lost_percent": receiver.get("lost_percent"),
        })
        progress("PASS: server-confirmed UL traffic: " + label)

    try:
        progress("Checking images and laboratory address availability")
        image(CLIENT, CLIENT_ID)
        image(CHECKER, CHECKER_ID)
        net = json.loads(output(["network", "inspect", "docker_open5gs_default"]))[0]
        for endpoint in net.get("Containers", {}).values():
            address = endpoint.get("IPv4Address", "").split("/")[0]
            require(address not in ("172.22.0.160", "172.22.0.161", "172.22.0.151"),
                    "Laboratory address already occupied: " + address)
        baseline_ids = output(["ps", "-q", "--no-trunc"]).split()
        require(baseline_ids, "No running baseline containers found")
        baseline = snapshot(baseline_ids)
        summary["baseline_before"] = baseline

        configuration = runpy.run_path(
            str(ROOT / "test/ocudu/prepare-slice-online.py")
        )["prepare"](ROOT, dest / "config")
        summary["configuration"] = configuration
        config = dest / "config/gnb.yml"

        progress("Validating generated configuration before live startup")
        cid = temporary_container([
            "--network", "none",
            "--mount", f"type=bind,source={config.parent},target=/config,readonly",
            "--entrypoint", "timeout", CHECKER_ID,
            "--signal=TERM", "--kill-after=3s", "20s",
            "/build/ocudu/apps/gnb_split_8/gnb",
            "-c", "/config/gnb.yml", "--dryrun",
        ])
        result = invoke(["start", "-a", cid], timeout=35, check=False)
        text = logs(cid)
        (dest / "configuration-check.log").write_text(text)
        state = json.loads(output(["inspect", cid]))[0]["State"]
        require(result.returncode == 0 and state["ExitCode"] == 0
                and not state["Running"] and not state["OOMKilled"]
                and text.count("LAB_CONFIG_VALIDATION_PASSED") == 1,
                "Generated configuration validation failed")

        env = dest / "compose.env"
        env.write_text("OCUDU_SLICE_CONFIG=" + str(config) + "\n")
        env.chmod(0o600)
        compose = [
            "compose", "--project-name", project, "--env-file", str(env),
            "-f", str(ROOT / "deploy/ocudu/compose.zmq.yaml"),
            "-f", str(ROOT / "deploy/ocudu/compose.slice-online.yaml"),
            "-f", str(ROOT / "deploy/ocudu/compose.slice-ul-drain.yaml"),
            "--profile", "ue",
        ]
        resolved = json.loads(output(compose + ["config", "--format", "json"]))
        require(set(resolved["services"]) == {"gnb", "nrue", "traffic"},
                "Unexpected resolved services")
        for name, expected in IMAGE_IDS.items():
            service = resolved["services"][name]
            require(service["image"].endswith("@" + expected)
                    and service.get("pull_policy") == "never"
                    and not service.get("ports"),
                    "Unexpected resolved image or ports: " + name)
            image(service["image"], expected)
            for mount in service.get("volumes", []):
                require(mount.get("type") == "bind"
                        and mount.get("read_only") is True
                        and Path(mount["source"]).is_file(),
                        "Missing or writable bind mount: " + name)

        progress("Starting independent single-cell gNB and UE")
        touched = True
        result = invoke(compose + [
            "up", "-d", "--no-build", "--pull", "never", "gnb", "nrue", "traffic",
        ], timeout=60, check=False)
        (dest / "startup.log").write_text(result.stdout + result.stderr)
        require(result.returncode == 0, "Compose startup failed")
        for name in ("gnb", "nrue", "traffic"):
            cid = output(compose + ["ps", "-q", name])
            require(cid and len(cid.splitlines()) == 1,
                    "Expected one test container: " + name)
            containers[name] = cid
        summary["test_before"] = {
            name: identity(cid) for name, cid in containers.items()
        }
        require(all(value["running"] and not value["oom_killed"]
                    for value in summary["test_before"].values()),
                "Test service not running")

        progress("Waiting for UE tunnel and remote-control listener; limit 90 seconds")
        deadline = time.monotonic() + 90
        while True:
            check_processes()
            address = invoke([
                "exec", containers["nrue"], "ip", "-4", "-j",
                "addr", "show", "dev", "oaitun_ue1",
            ], timeout=10, check=False)
            addresses = []
            if address.returncode == 0:
                addresses = [
                    value["local"] for interface in json.loads(address.stdout)
                    for value in interface.get("addr_info", [])
                    if value.get("family") == "inet"
                ]
            gnb_log = logs(containers["gnb"])
            if (len(addresses) == 1 and
                    "Remote control server listening on 127.0.0.1:8001" in gnb_log):
                summary["ue_address"] = addresses[0]
                break
            require(time.monotonic() < deadline,
                    "UE tunnel or remote-control listener readiness timeout")
            time.sleep(1)
        ping("before-control")
        ul_load("baseline")
        progress("UE baseline connectivity passed")

        for label, maximum in (("limited", 20), ("restored", 100)):
            check_processes()
            before = logs(containers["gnb"])
            (dest / ("gnb." + label + ".before.log")).write_text(before)
            phase = {"name": label, "min_ratio": 0, "max_ratio": maximum}
            summary["phases"].append(phase)
            progress("Sending one slice request: max=" + str(maximum))
            cid = temporary_container([
                "--network", "container:" + containers["gnb"],
                CLIENT_ID, "--plmn", "00101", "--sst", "1",
                "--min-ratio", "0", "--max-ratio", str(maximum),
            ])
            summary["control_requests_attempted"] += 1
            result = invoke(["start", "-a", cid], timeout=25, check=False)
            text = logs(cid)
            (dest / ("control-" + label + ".log")).write_text(text)
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
            require(result.returncode == 0
                    and len([r for r in records if r.get("event") == "request"]) == 1
                    and len([r for r in records if r.get("event") == "response"]) == 1
                    and any(r.get("passed") is True and r.get("requests_sent") == 1
                            for r in records),
                    "Remote command response validation failed: " + label)
            summary["control_requests_sent"] += 1
            phase["response_validated"] = True

            deadline = time.monotonic() + 15
            while True:
                check_processes()
                after = logs(containers["gnb"])
                require(after.startswith(before), "gNB log history changed")
                delta = after[len(before):]
                events = re.findall(r"- Slice Reconfig: cell=0\b", delta)
                if events:
                    break
                require(time.monotonic() < deadline,
                        "Scheduler slice reconfiguration event missing: " + label)
                time.sleep(0.5)
            require(len(events) == 1, "Duplicated scheduler update event: " + label)
            phase["scheduler_event_validated"] = True
            progress("Scheduler update observed; checking five UPF pings")
            ul_load(label)
            ping(label)
            phase["pings_passed"] = 5
            after = logs(containers["gnb"])
            (dest / ("gnb." + label + ".after.log")).write_text(after)
            require(after.startswith(before)
                    and len(re.findall(r"- Slice Reconfig: cell=0\b",
                                       after[len(before):])) == 1,
                    "Unexpected additional slice update: " + label)
            check_processes()
            progress("PASS: " + label + " response, scheduler event and 5/5 pings")

        require(len(summary["ul_load"]) == 3,
                "Expected three server-confirmed UL load phases")
        require(summary["control_requests_sent"] == 2,
                "Expected two successful control requests")
        require(snapshot(baseline_ids) == baseline,
                "An existing baseline process changed")
        source = ROOT / configuration["source"]
        require(hashlib.sha256(source.read_bytes()).hexdigest()
                == configuration["source_sha256"],
                "Original configuration changed")
        summary["checks_passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        progress("Validation stopped: " + str(error))
    finally:
        progress("Collecting logs and removing only this test's containers")
        for name, cid in containers.items():
            try:
                (dest / (name + ".final.log")).write_text(logs(cid))
                summary.setdefault("test_after", {})[name] = identity(cid)
            except Exception as error:
                summary["cleanup_errors"].append("Evidence: " + str(error))
        if touched:
            try:
                result = invoke(compose + ["down", "--timeout", "15"], timeout=50)
                (dest / "cleanup.log").write_text(result.stdout + result.stderr)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        for cid in auxiliary:
            try:
                output(["rm", "-f", cid])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        try:
            require(not output([
                "ps", "-aq", "--filter",
                "label=com.docker.compose.project=" + project,
            ]), "Test Compose containers remain")
            if baseline is not None:
                summary["baseline_after"] = snapshot(baseline_ids)
                require(summary["baseline_after"] == baseline,
                        "Existing baseline process identity changed")
        except Exception as error:
            summary["cleanup_errors"].append(str(error))
        summary["passed"] = bool(
            summary.get("checks_passed") and not summary["cleanup_errors"]
        )
        (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
        progress("Evidence: " + str(dest))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
