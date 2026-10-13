#!/usr/bin/env python3
"""Validate E2-directed independent real NR DL scheduler executions."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def audit_execution(directory, execution):
    from collections import defaultdict
    policies = {}
    grants = defaultdict(list)
    for line in (directory / "scheduler.log").read_text().splitlines():
        if line.startswith("PRB_POLICY "):
            item = json.loads(line[len("PRB_POLICY "):])
            key = (item["frame"], item["slot"])
            require(key not in policies, "Duplicate policy evidence")
            policies[key] = item
        elif line.startswith("PRB_GRANT "):
            item = json.loads(line[len("PRB_GRANT "):])
            require(item["rnti"] in (0x1234, 0x1235, 0x1236), "Unexpected UE")
            require(item["rb_size"] > 0 and item["rb_start"] >= 0
                    and item["rb_start"] + item["rb_size"] <= item["bwp_size"]
                    and item["tb_bytes"] > 0, "Invalid actual grant")
            grants[(item["frame"], item["slot"])].append(item)
    require(len(policies) == 200 and bool(grants)
            and set(grants).issubset(policies), "Incomplete raw evidence")
    totals = [0, 0, 0]
    quotas = execution["quotas"]
    for key, policy in policies.items():
        actual = [0, 0, 0]
        items = grants.get(key, [])
        for g in items:
            s = g["rnti"] - 0x1234
            actual[s] += g["rb_size"]
            totals[s] += g["rb_size"]
        require(policy["caps"] == [policy["available"] * q // 100 for q in quotas],
                "Raw quota mismatch")
        require(actual == policy["used"]
                and all(u <= c for u, c in zip(actual, policy["caps"])),
                "Actual PRB cap mismatch")
        ordered = sorted(items, key=lambda g: g["bwp_start"] + g["rb_start"])
        for a, b in zip(ordered, ordered[1:]):
            require(a["bwp_start"] + a["rb_start"] + a["rb_size"]
                    <= b["bwp_start"] + b["rb_start"], "Overlapping actual grants")
    require(totals == execution["total_prb"], "Execution summary mismatch")
    require(all(t == 0 if q == 0 else t > 0 for q, t in zip(quotas, totals)),
            "Unexpected slice service")
    return totals

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/oai-e2-prb-validation"))
    parser.add_argument("--project", default="oai-pi-prb-execution-lab")
    parser.add_argument("--xapp-image", default="limx59/oai-pi-flexric-xapp:arm64-prb-execution-test")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_dir.resolve()))
    print(f"Evidence: {output}", flush=True)
    root = Path(__file__).resolve().parents[2]
    config = root / "deploy/oai-flexric/config/emulator/xapp.conf"
    docker = ["sudo", "docker"]
    agents = [f"{args.project}-emulator-1",
              f"{args.project}-emulator-2-1",
              f"{args.project}-emulator-3-1"]
    names = [f"{args.project}-ric-1", *agents]
    temporary = set()
    summary = {"passed": False, "cases": [], "cleanup_errors": [],
               "scope": "E2-triggered independent real NR DL scheduler simulations"}

    def run(command, timeout=25):
        return subprocess.run(command, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    def identities():
        result = run(docker + ["inspect", *names])
        result.check_returncode()
        records = json.loads(result.stdout)
        require(all(r["State"]["Running"] for r in records), "A process stopped")
        return {r["Name"].lstrip("/"): {
            "id": r["Id"], "image": r["Image"], "pid": r["State"]["Pid"],
            "started_at": r["State"]["StartedAt"], "restart_count": r["RestartCount"],
        } for r in records}

    try:
        before = identities()
        (output / "before.json").write_text(json.dumps(before, indent=2) + "\n")
        cases = [
            ("invalid-empty", 1, "", False, "none"),
            ("invalid-sum", 1, "45,40,14", False, "none"),
            ("invalid-negative", 1, "-1,50,51", False, "none"),
            ("invalid-overflow", 1, "999999999999,0,0", False, "none"),
            ("missing-node", 99, "45,40,15", False, "oai-pi-flexric-lab"),
            ("node-1", 1, "45,40,15", True, "oai-pi-flexric-lab"),
            ("node-2", 2, "45,40,15", True, "oai-pi-flexric-lab"),
            ("node-3", 3, "45,40,15", True, "oai-pi-flexric-lab"),
            ("node-2-swapped", 2, "15,40,45", True, "oai-pi-flexric-lab"),
            ("node-2-zero", 2, "0,50,50", True, "oai-pi-flexric-lab"),
            ("node-2-restored", 2, "45,40,15", True, "oai-pi-flexric-lab"),
        ]
        for label, node, quotas, success, network in cases:
            started = datetime.now(timezone.utc).isoformat()
            name = "oai-prb-xapp-" + uuid.uuid4().hex[:10]
            temporary.add(name)
            command = docker + [
                "run", "--rm", "--pull", "never", "--name", name,
                "--network", network,
                "-e", f"XAPP_SLICE_NODE_ID={node}",
                "-e", f"XAPP_PRB_QUOTAS={quotas}",
                "--mount", f"type=bind,src={config},dst=/usr/local/etc/flexric/xapp.conf,readonly",
                args.xapp_image, "xapp_prb_control.py",
                "-c", "/usr/local/etc/flexric/xapp.conf",
            ]
            try:
                result = run(command, timeout=60)
            except subprocess.TimeoutExpired as error:
                def decode(value):
                    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                (output / f"{label}-xapp.log").write_text(
                    decode(error.stdout) + decode(error.stderr))
                raise
            text = result.stdout + result.stderr
            (output / f"{label}-xapp.log").write_text(text)
            if success:
                require(result.returncode == 0, f"{label}: xApp failed")
                require(text.count("CONTROL-REQUEST tx") == 1, f"{label}: transmission count")
                require(text.count("Successfully received CONTROL-ACK") == 1,
                        f"{label}: ACK count")
            else:
                require(result.returncode != 0, f"{label}: rejection expected")
                require("CONTROL-REQUEST tx" not in text, f"{label}: unexpected control")
                marker = "XAPP_PRB_QUOTAS" if label.startswith("invalid") else "No control sent"
                require(marker in text, f"{label}: missing explicit rejection")
                if network == "none":
                    require("E42 SETUP-REQUEST tx" not in text, f"{label}: initialized before rejection")

            case = {"label": label, "node": node, "quotas": quotas, "passed": True}
            for index, agent in enumerate(agents, 1):
                logs = run(docker + ["logs", "--since", started, agent])
                logs.check_returncode()
                text = logs.stdout + logs.stderr
                (output / f"{label}-node-{index}.log").write_text(text)
                records = [json.loads(line[len("E2_PRB_EXECUTION "):])
                           for line in text.splitlines()
                           if line.startswith("E2_PRB_EXECUTION ")]
                if success and index == node:
                    require(len(records) == 1, f"{label}: target execution count")
                    record = records[0]
                    require(record["passed"] is True and record["actual_grants_verified"] is True,
                            f"{label}: scheduler verification")
                    require(record["node"] == str(node), f"{label}: wrong executing node")
                    require(record["quotas"] == list(map(int, quotas.split(","))),
                            f"{label}: received quota mismatch")
                    require(text.count("SLICE CONTROL ADD rx") == 1,
                            f"{label}: target reception count")
                    evidence = record["evidence"]
                    require(evidence.startswith("/tmp/e2-prb-execution-")
                            and "/" not in evidence[len("/tmp/"):],
                            "Unexpected evidence path")
                    copied = run(docker + ["cp", f"{agent}:{evidence}", str(output / label)])
                    copied.check_returncode()
                    owned = run(docker[:1] + [
                        "chown", "-R", f"{os.getuid()}:{os.getgid()}",
                        str(output / label)])
                    owned.check_returncode()
                    audit_execution(output / label, record)
                    case["independent_raw_audit"] = True
                    case["execution"] = record
                else:
                    require(not records and "SLICE CONTROL ADD rx" not in text,
                            f"{label}: non-target execution")
            require(identities() == before, f"{label}: process identity changed")
            summary["cases"].append(case)
            print(f"PASS: {label}", flush=True)
        summary["all_four_processes_unchanged"] = True
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        for name in temporary:
            result = run(docker + ["rm", "-f", name])
            if result.returncode and "No such container" not in result.stderr:
                summary["cleanup_errors"].append(result.stderr)
        if summary["cleanup_errors"]:
            summary["passed"] = False
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Logs and summary: {output}", flush=True)
    require(summary["passed"], "Validation or cleanup failed")
    print("PASS: directed PRB execution, rejection, evidence and process checks.", flush=True)

if __name__ == "__main__":
    main()
