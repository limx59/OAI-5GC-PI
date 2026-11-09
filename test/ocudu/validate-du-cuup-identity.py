#!/usr/bin/env python3
"""Verify that one FlexRIC RIC distinguishes OCUDU DU and CU-UP agents."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
NETWORK = "docker_open5gs_default"
GNB_IP = "172.22.0.160"
BASE_RIC_IP = "172.22.0.162"
TEST_RIC_IP = "172.22.0.163"
RIC_IMAGE = "limx59/oai-pi-ocudu-flexric-ric:arm64-kpm-csv-metadata-test"
GNB_IMAGE = (
    "limx59/oai-pi-ocudu-gnb:arm64-kpm-pdcp-provenance-clock-test"
    "@sha256:99a169ba550db2995c41d5ba401b3ef1d2ca820b83f7a481caf96a2efdffd620"
)
PROBE_IMAGE = (
    "limx59/oai-pi-ocudu-flexric-xapp:arm64-xapp-compatibility-test"
    "@sha256:bc6c6f46d8338bfab83d2ccbf7bd578028680d0c114cc99cd72b31646156d587"
)

PROBE = """\
from collections import Counter
import json
import sys
import time

import xapp_kpm as demo

ric = demo.ric
ric.init(sys.argv)
expected = Counter({"ngran_gNB_DU": 1, "ngran_gNB_CUUP": 1})
deadline = time.monotonic() + 25
while True:
    nodes = [
        {
            "gnb_id": int(node.id.nb_id.nb_id),
            "role": ric.get_e2ap_ngran_name(node.id.type),
        }
        for node in ric.conn_e2_nodes()
    ]
    roles = Counter(node["role"] for node in nodes if node["gnb_id"] == 420)
    passed = roles == expected
    if passed or time.monotonic() >= deadline:
        print(json.dumps({"passed": passed, "nodes": nodes}), flush=True)
        sys.exit(0 if passed else 1)
    time.sleep(0.5)
"""


def docker(*args, timeout=60, output=None):
    return subprocess.run(
        ["sudo", "docker", *args],
        cwd=ROOT,
        check=True,
        text=True,
        timeout=timeout,
        stdout=output if output is not None else subprocess.PIPE,
        stderr=subprocess.STDOUT if output is not None else None,
    ).stdout


def write_config(dest, name, source, changes):
    text = subprocess.check_output(
        ["git", "show", f"HEAD:{source}"], cwd=ROOT, text=True
    )
    for old, new in changes:
        if text.count(old) != 1:
            raise RuntimeError(f"Unexpected config anchor in {source}: {old}")
        text = text.replace(old, new, 1)
    (dest / name).write_text(text, encoding="utf-8")


def process_identity(compose, service):
    cid = docker(*compose, "ps", "-q", service).strip()
    if len(cid.splitlines()) != 1:
        raise RuntimeError(f"Expected one running {service} container")
    item = json.loads(docker("inspect", cid))[0]
    state = item["State"]
    if not state["Running"]:
        raise RuntimeError(f"{service} is not running")
    return {
        "id": item["Id"],
        "pid": state["Pid"],
        "started_at": state["StartedAt"],
    }


def validate_lifecycle(compose, run_probe, dest):
    def identity(service):
        return process_identity(compose, service)

    def require_restart(before, after, service):
        if before["id"] != after["id"] or before["started_at"] == after["started_at"]:
            raise RuntimeError(f"Expected a new {service} process in the same container")

    initial_nodes = run_probe("probe-before-ric-restart.log")
    initial = {service: identity(service) for service in ("ric", "gnb")}

    print("Restarting only the temporary RIC", flush=True)
    docker(*compose, "restart", "ric")
    ric_after = identity("ric")
    require_restart(initial["ric"], ric_after, "RIC")
    time.sleep(2)
    reconnected = run_probe("probe-after-ric-restart.log")
    if identity("gnb") != initial["gnb"] or identity("ric") != ric_after:
        raise RuntimeError("Unexpected process change during RIC restart validation")

    print("Stopping only the temporary gNB", flush=True)
    docker(*compose, "stop", "gnb")
    stopped = json.loads(docker("inspect", initial["gnb"]["id"]))[0]["State"]
    if stopped["Running"]:
        raise RuntimeError("Temporary gNB is still running")
    expected = 'expected = Counter({"ngran_gNB_DU": 1, "ngran_gNB_CUUP": 1})'
    if PROBE.count(expected) != 1:
        raise RuntimeError("Unexpected probe layout")
    absence_probe = PROBE.replace(expected, "expected = Counter()\ntime.sleep(2)", 1)
    absent = run_probe("probe-after-gnb-stop.log", absence_probe)
    if identity("ric") != ric_after:
        raise RuntimeError("RIC process changed while gNB was stopped")

    print("Starting the same temporary gNB container", flush=True)
    docker(*compose, "start", "gnb")
    gnb_after = identity("gnb")
    require_restart(initial["gnb"], gnb_after, "gNB")
    registered = run_probe("probe.log")
    if identity("ric") != ric_after or identity("gnb") != gnb_after:
        raise RuntimeError("Unexpected process change during gNB restart validation")

    result = {
        "initial_processes": initial,
        "ric_after_restart": ric_after,
        "gnb_after_restart": gnb_after,
        "initial_nodes": initial_nodes["nodes"],
        "nodes_after_ric_restart": reconnected["nodes"],
        "nodes_while_gnb_stopped": absent["nodes"],
        "nodes_after_gnb_restart": registered["nodes"],
        "gnb_unchanged_across_ric_restart": True,
        "ric_unchanged_across_gnb_stop_start": True,
    }
    (dest / "lifecycle.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def validate_subscription_targeting(compose, run_probe, dest):
    probe_source = Path(__file__).with_name(
        "probe-du-cuup-subscription-targeting.py"
    ).read_text(encoding="utf-8")
    template = (dest / "xapp.conf").read_text(encoding="utf-8")
    cases = (
        ("du", "ngran_gNB_DU", 4, "DRB.UEThpDl", "probe-du.log"),
        ("cuup", "ngran_gNB_CUUP", 1, "DRB.PacketSuccessRateUlgNBUu", "probe-cuup.log"),
        ("cucp", "ngran_gNB", 1, "RRC.ConnEstabAtt", "probe.log"),
    )
    for label, role, style, metric, _ in cases:
        config = template
        for old, new in (
            ("format = 4,", f"format = {style},"),
            ('ran_type = "ngran_gNB_DU"', f'ran_type = "{role}"'),
            ('{ name = "DRB.UEThpDl" },\n'
             '          { name = "DRB.UEThpUl" }',
             f'{{ name = "{metric}" }}'),
        ):
            if config.count(old) != 1:
                raise RuntimeError(f"Unexpected xApp config anchor: {old}")
            config = config.replace(old, new, 1)
        with (dest / f"xapp-{label}.conf").open("x", encoding="utf-8") as stream:
            stream.write(config)

    docker(*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "nrue")
    ue = docker(*compose, "ps", "-q", "nrue").strip()
    if len(ue.splitlines()) != 1:
        raise RuntimeError("Expected one running temporary UE")
    deadline = time.monotonic() + 45
    while True:
        ready = subprocess.run(
            ["sudo", "docker", "exec", ue, "ip", "-4", "-o",
             "addr", "show", "dev", "oaitun_ue1"],
            capture_output=True, text=True, timeout=10,
        )
        if ready.returncode == 0 and " inet " in ready.stdout:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Temporary UE tunnel did not become ready")
        time.sleep(1)

    results = []
    for label, role, style, metric, log_name in cases:
        print(f"=== Subscribe to {role}: {metric} ===", flush=True)
        result = run_probe(
            log_name, probe_source, config=dest / f"xapp-{label}.conf",
            environment={
                "TARGET_ROLE": role,
                "TARGET_METRIC": metric,
                "OAI_PI_KPM_REPORT_STYLE": style,
            },
        )
        results.append(result)
        print(json.dumps(result), flush=True)
        (dest / "subscription-targeting.json").write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lifecycle", action="store_true",
        help="Also verify RIC restart, gNB exit cleanup and Agent reconnection.",
    )
    parser.add_argument(
        "--include-cu-cp", action="store_true",
        help="Verify DU, CU-UP and CU-CP identities in one RIC snapshot.",
    )
    parser.add_argument(
        "--subscription-targeting", action="store_true",
        help="Verify KPM subscription targeting with all three Agents online.",
    )
    args = parser.parse_args()
    if args.subscription_targeting:
        if args.lifecycle:
            parser.error("--subscription-targeting and --lifecycle must run separately")
        args.include_cu_cp = True
    if args.include_cu_cp and args.lifecycle:
        parser.error("--include-cu-cp and --lifecycle must run separately")
    network = json.loads(docker("network", "inspect", NETWORK))[0]
    test_addresses = {GNB_IP, TEST_RIC_IP}
    if args.subscription_targeting:
        test_addresses.add("172.22.0.161")
    for endpoint in (network.get("Containers") or {}).values():
        address = endpoint.get("IPv4Address", "").split("/")[0]
        if address in test_addresses:
            raise RuntimeError(f"Test address {address} is occupied by {endpoint['Name']}")
    for image in (RIC_IMAGE, GNB_IMAGE, PROBE_IMAGE):
        docker("image", "inspect", image)

    evidence_root = Path.home() / "Work/oai-test-evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    prefix = (
        "ocudu-three-agent-identity-" if args.include_cu_cp
        else "ocudu-du-cuup-identity-"
    )
    dest = Path(tempfile.mkdtemp(prefix=prefix, dir=evidence_root))
    dest.chmod(0o755)
    print(f"Evidence: {dest}", flush=True)
    project = f"ocudu-node-{uuid.uuid4().hex[:12]}"

    gnb_changes = [
        ("  enable_du_e2: false", "  enable_du_e2: true"),
        (f"  addrs: [{BASE_RIC_IP}]", f"  addrs: [{TEST_RIC_IP}]"),
    ]
    probe_source = PROBE
    if args.include_cu_cp:
        gnb_changes.append(
            ("  enable_cu_cp_e2: false", "  enable_cu_cp_e2: true")
        )
        expected = 'expected = Counter({"ngran_gNB_DU": 1, "ngran_gNB_CUUP": 1})'
        if PROBE.count(expected) != 1:
            raise RuntimeError("Unexpected probe layout")
        # This configuration advertises CU-CP as ngran_gNB.
        probe_source = PROBE.replace(
            expected,
            'expected = Counter({"ngran_gNB_DU": 1, "ngran_gNB_CUUP": 1, "ngran_gNB": 1})',
            1,
        )
    write_config(dest, "gnb.yml", "test/ocudu/config/gnb-zmq-pdcp.yml", gnb_changes)
    for name in ("ric.conf", "xapp.conf"):
        write_config(dest, name, f"deploy/ocudu/config/{name}", [
            (f'NearRT_RIC_IP = "{BASE_RIC_IP}"', f'NearRT_RIC_IP = "{TEST_RIC_IP}"'),
        ])
    (dest / "probe.py").write_text(PROBE, encoding="utf-8")

    override = dest / "compose.identity.yaml"
    override.write_text(json.dumps({"services": {
        "ric": {
            "image": RIC_IMAGE,
            "networks": {"core": {"ipv4_address": TEST_RIC_IP}},
            "volumes": [f"{dest}/ric.conf:/usr/local/etc/flexric/ric.conf:ro"],
        },
        "gnb": {
            "image": GNB_IMAGE,
            "volumes": [f"{dest}/gnb.yml:/etc/ocudu/gnb.yml:ro"],
        },
    }}, indent=2) + "\n", encoding="utf-8")
    compose = (
        "compose", "-p", project,
        "-f", "deploy/ocudu/compose.zmq.yaml",
        "-f", "deploy/ocudu/compose.e2.yaml",
        "-f", "test/ocudu/patches/compose.kpm-collection-clock.yaml",
        "-f", str(override),
    )
    services = ("ric", "gnb")
    if args.subscription_targeting:
        compose += ("--profile", "ue")
        services += ("nrue",)
    resolved = docker(*compose, "config", "--format", "json")
    (dest / "compose.resolved.json").write_text(resolved, encoding="utf-8")

    lifecycle = None
    error = None
    cleanup_errors = []
    probe_name = f"{project}-probe"
    probe_started = False
    try:
        docker(*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "ric")
        time.sleep(2)
        docker(*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "gnb")
        time.sleep(3)
        def run_probe(log_name, probe_source=PROBE, config=None, environment=None):
            config = dest / "xapp.conf" if config is None else config
            env_args = []
            for key, value in (environment or {}).items():
                env_args.extend(("-e", f"{key}={value}"))
            nonlocal probe_started
            (dest / "probe.py").write_text(probe_source, encoding="utf-8")
            with (dest / log_name).open("w", encoding="utf-8") as log:
                probe_started = True
                docker(
                    "run", "--name", probe_name, "--rm", "--pull", "never",
                    "--network", NETWORK, "--ulimit", "core=0", *env_args,
                    "-v", f"{dest}/probe.py:/opt/ocudu-xapp-compatibility/node_identity.py:ro",
                    "-v", f"{config}:/usr/local/etc/flexric/xapp.conf:ro",
                    "--entrypoint", "timeout", PROBE_IMAGE,
                    "--signal=INT", "--kill-after=5s", "40s",
                    "python3", "-B", "-u", "/opt/ocudu-xapp-compatibility/node_identity.py",
                    "-c", "/usr/local/etc/flexric/xapp.conf",
                    output=log,
                )
            probe_started = False

            result = None
            setup_received = False
            for line in (dest / log_name).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if "E42 SETUP-RESPONSE rx" in line:
                    setup_received = True
                if setup_received and line.startswith('{"passed":'):
                    result = json.loads(line)
            if result is None or result.get("passed") is not True:
                raise RuntimeError(f"No passing snapshot after E42 setup in {log_name}")
            return result

        if args.lifecycle:
            lifecycle = validate_lifecycle(compose, run_probe, dest)
        elif args.subscription_targeting:
            validate_subscription_targeting(compose, run_probe, dest)
        else:
            run_probe("probe.log", probe_source)
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or type(exc).__name__
    finally:
        if probe_started:
            try:
                remaining = docker("ps", "-aq", "--filter", f"name=^/{probe_name}$").strip()
                if remaining:
                    docker("rm", "-f", remaining)
            except Exception as exc:
                cleanup_errors.append(f"Probe cleanup: {exc}")
        try:
            with (dest / "ran-ric.log").open("w", encoding="utf-8") as log:
                docker(*compose, "logs", "--no-color", *services, output=log)
        except Exception as exc:
            cleanup_errors.append(f"Log collection: {exc}")
        try:
            docker(*compose, "down")
        except Exception as exc:
            cleanup_errors.append(f"Compose cleanup: {exc}")

    probe_log = dest / "probe.log"
    nodes = []
    probe_passed = False
    if probe_log.is_file():
        for line in probe_log.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith('{"passed":'):
                result = json.loads(line)
                probe_passed = result["passed"] is True
                nodes = result["nodes"]
    summary = {
        "passed": probe_passed and error is None and not cleanup_errors,
        "nodes": nodes,
        "error": error,
        "cleanup_errors": cleanup_errors,
        "lifecycle": lifecycle,
    }
    report = json.dumps(summary, indent=2) + "\n"
    (dest / "summary.json").write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Evidence: {dest}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
