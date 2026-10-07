#!/usr/bin/env python3
"""Validate running FlexRIC emulator topologies through Docker."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

DIRECTORY = Path(__file__).resolve().parents[2] / "deploy/oai-flexric"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("multi-agent", "multi-ric"), required=True)
    parser.add_argument("--checks", nargs="+",
                        choices=("config", "invalid-id", "nodes", "kpm", "control"),
                        default=("config", "nodes", "kpm", "control"))
    parser.add_argument("--emulator-image", default="limx59/flexric-emulator:arm64-multi-agent")
    parser.add_argument("--xapp-image", default="limx59/flexric-xapp:arm64-multi-agent")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/tmp/flexric-topology-validation"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    docker = ["sudo", "docker"]
    compose = ["sudo", "env",
               f"FLEXRIC_EMULATOR_IMAGE={args.emulator_image}",
               f"FLEXRIC_XAPP_IMAGE={args.xapp_image}", "docker", "compose"]
    files = ["compose.emulator.yaml", "compose.multi-agent.yaml"]
    if args.scenario == "multi-ric":
        files.append("compose.multi-ric.yaml")
    for filename in files:
        compose += ["-f", str(DIRECTORY / filename)]

    def run(command, label, status=0, timeout=45):
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        path = args.output_dir / f"{args.scenario}-{label}.log"
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == status,
                f"{label}: exit={result.returncode}, expected={status}; inspect {path}")
        return result.stdout + result.stderr

    groups = [("a", {1, 2, 3}, "xapp-nodes", "xapp-kpm")]
    if args.scenario == "multi-ric":
        groups = [
            ("a", {1, 2}, "xapp-nodes", "xapp-kpm"),
            ("b", {3}, "xapp-nodes-ric2", "xapp-kpm-ric2"),
        ]

    if "config" in args.checks:
        command = compose + ["--profile", "tools", "config", "--format", "json"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        path = args.output_dir / f"{args.scenario}-config.log"
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        require(result.returncode == 0, f"Compose configuration failed; inspect {path}")
        services = json.loads(result.stdout)["services"]
        addresses = {
            "ric": "172.29.0.10", "emulator": "172.29.0.20",
            "emulator-2": "172.29.0.21", "emulator-3": "172.29.0.22",
        }
        if args.scenario == "multi-ric":
            addresses["ric-2"] = "172.29.0.11"
        for name, address in addresses.items():
            service = services[name]
            require(service["networks"]["lab"]["ipv4_address"] == address,
                    f"{name}: incorrect address")
            require("build" in service, f"{name}: build settings missing")
        for name, node in (("emulator", "1"), ("emulator-2", "2"), ("emulator-3", "3")):
            require(services[name]["environment"]["FLEXRIC_EMULATOR_NB_ID"] == node,
                    f"{name}: incorrect node ID")
            require(services[name]["image"] == args.emulator_image,
                    f"{name}: incorrect image")
        if args.scenario == "multi-ric":
            for name, filename, target in (
                ("ric-2", "ric.conf", "/usr/local/etc/flexric/ric.conf"),
                ("emulator-3", "e2agent.conf", "/usr/local/etc/flexric/e2agent.conf"),
                ("xapp-nodes-ric2", "xapp.conf", "/usr/local/etc/flexric/xapp.conf"),
                ("xapp-kpm-ric2", "xapp.conf", "/usr/local/etc/flexric/xapp.conf"),
            ):
                mounts = [v for v in services[name]["volumes"] if v["target"] == target]
                require(len(mounts) == 1, f"{name}: incorrect configuration mounts")
                require(Path(mounts[0]["source"]) ==
                        DIRECTORY / "config/multi-ric" / filename,
                        f"{name}: incorrect RIC B configuration")
                require(mounts[0].get("read_only"), f"{name}: writable configuration")
        print("PASS: merged configuration")

    if "invalid-id" in args.checks:
        for index, value in enumerate(("", "0", "-1", "abc", "65536",
                                       "999999999999999999999999")):
            text = run(docker + ["run", "--rm", "--network", "none",
                                "-e", f"FLEXRIC_EMULATOR_NB_ID={value}",
                                args.emulator_image],
                       f"invalid-id-{index}", status=1, timeout=20)
            require("must be an integer in 1..65535" in text,
                    f"Invalid ID {value!r}: expected validation message missing")
        print("PASS: six invalid node IDs rejected")

    if "nodes" in args.checks:
        for label, expected, service, _ in groups:
            text = run(compose + ["--profile", "tools", "run", "-T", "--rm",
                                  "--no-deps", service], f"{label}-nodes")
            found = {int(n) for n in re.findall(
                r"^\s*\d+\s+(\d+)\s+505\s+1\s+gNB\s*$", text, re.MULTILINE)}
            require(found == expected, f"RIC {label}: unexpected nodes {sorted(found)}")
            require(f"Connected E2 nodes: {len(expected)}" in text,
                    f"RIC {label}: unexpected node count")
            print(f"PASS: RIC {label.upper()} nodes={sorted(found)}")

    if "kpm" in args.checks:
        def check_kpm(group):
            label, expected, _, service = group
            text = run(compose + ["--profile", "tools", "run", "-T", "--rm",
                                  "--no-deps", service], f"{label}-kpm")
            subscribed = {int(n) for n in re.findall(r"Subscribed: node=(\d+)", text)}
            reported = {int(n) for n in re.findall(r"KPM node=(\d+)", text)}
            require(subscribed == reported == expected,
                    f"RIC {label}: unexpected KPM nodes")
            require(text.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == len(expected),
                    f"RIC {label}: subscription cleanup incomplete")
            return f"PASS: RIC {label.upper()} KPM nodes={sorted(reported)}"
        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            for message in pool.map(check_kpm, groups):
                print(message)

    if "control" in args.checks:
        since = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        if args.scenario == "multi-agent":
            cases = [("a", "emulator", 99, 100, 1),
                     ("a", "emulator", 2, 3, 0)]
            receiver, target_cgi = "emulator-2", 768
        else:
            cases = [("a", "emulator", 3, 4, 1),
                     ("b", "multi-ric", 3, 4, 0)]
            receiver, target_cgi = "emulator-3", 1024
        for label, folder, node, target, status in cases:
            config = DIRECTORY / "config" / folder / "xapp.conf"
            text = run(docker + [
                "run", "--rm", "--network", "oai-pi-flexric-lab",
                "--mount", f"type=bind,src={config},"
                "dst=/usr/local/etc/flexric/xapp.conf,readonly",
                "-e", "XAPP_RAN_UE_ID=1",
                "-e", f"XAPP_SOURCE_NR_CGI={node << 8}",
                "-e", f"XAPP_TARGET_NR_CGI={target << 8}",
                "--entrypoint", "stdbuf", args.xapp_image,
                "-oL", "-eL", "/usr/local/bin/flexric/xApp/c/xapp_handover_control",
                "-c", "/usr/local/etc/flexric/xapp.conf",
            ], f"{label}-control-node{node}", status=status, timeout=25)
            if status:
                require(f"Lab node {node} not found; no control sent." in text
                        and "CONTROL-REQUEST tx" not in text,
                        "Missing-node control was not rejected correctly")
            else:
                require(f"Selected lab node: PLMN 505/01, node ID {node}" in text
                        and "Successfully received CONTROL-ACK" in text,
                        "Target selection or control acknowledgement failed")
        for service in ("emulator", "emulator-2", "emulator-3"):
            text = run(compose + ["logs", "--no-color", "--since", since, service],
                       f"{service}-control-reception")
            count = text.count("Recv control message for handover")
            require(count == (1 if service == receiver else 0),
                    f"{service}: unexpected control reception count {count}")
            if service == receiver:
                require(f"ran_ue_id 1 to target cell NR_CGI {target_cgi}" in text
                        and "CONTROL ACKNOWLEDGE tx" in text,
                        f"{service}: incorrect parameters or missing acknowledgement")
        print("PASS: missing-node rejection and targeted emulator control reception")

    print(f"Logs: {args.output_dir}")


if __name__ == "__main__":
    main()
