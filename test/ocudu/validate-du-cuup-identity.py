#!/usr/bin/env python3
"""Verify that one FlexRIC RIC distinguishes OCUDU DU and CU-UP agents."""

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


def main():
    network = json.loads(docker("network", "inspect", NETWORK))[0]
    for endpoint in (network.get("Containers") or {}).values():
        address = endpoint.get("IPv4Address", "").split("/")[0]
        if address in {GNB_IP, TEST_RIC_IP}:
            raise RuntimeError(f"Test address {address} is occupied by {endpoint['Name']}")
    for image in (RIC_IMAGE, GNB_IMAGE, PROBE_IMAGE):
        docker("image", "inspect", image)

    evidence_root = Path.home() / "Work/oai-test-evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-du-cuup-identity-", dir=evidence_root))
    dest.chmod(0o755)
    print(f"Evidence: {dest}", flush=True)
    project = f"ocudu-node-{uuid.uuid4().hex[:12]}"

    write_config(dest, "gnb.yml", "test/ocudu/config/gnb-zmq-pdcp.yml", [
        ("  enable_du_e2: false", "  enable_du_e2: true"),
        (f"  addrs: [{BASE_RIC_IP}]", f"  addrs: [{TEST_RIC_IP}]"),
    ])
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
    resolved = docker(*compose, "config", "--format", "json")
    (dest / "compose.resolved.json").write_text(resolved, encoding="utf-8")

    error = None
    cleanup_errors = []
    probe_name = f"{project}-probe"
    probe_started = False
    try:
        docker(*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "ric")
        time.sleep(2)
        docker(*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "gnb")
        time.sleep(3)
        with (dest / "probe.log").open("w", encoding="utf-8") as log:
            probe_started = True
            docker(
                "run", "--name", probe_name, "--rm", "--pull", "never",
                "--network", NETWORK, "--ulimit", "core=0",
                "-v", f"{dest}/probe.py:/opt/ocudu-xapp-compatibility/node_identity.py:ro",
                "-v", f"{dest}/xapp.conf:/usr/local/etc/flexric/xapp.conf:ro",
                "--entrypoint", "timeout", PROBE_IMAGE,
                "--signal=INT", "--kill-after=5s", "40s",
                "python3", "-B", "-u", "/opt/ocudu-xapp-compatibility/node_identity.py",
                "-c", "/usr/local/etc/flexric/xapp.conf",
                output=log,
            )
        probe_started = False
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
                docker(*compose, "logs", "--no-color", "ric", "gnb", output=log)
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
    }
    report = json.dumps(summary, indent=2) + "\n"
    (dest / "summary.json").write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Evidence: {dest}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
