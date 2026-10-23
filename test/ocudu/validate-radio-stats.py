#!/usr/bin/env python3
"""Validate DU scheduler PRB and RLC KPM statistics under UL/DL traffic."""

from datetime import datetime, timedelta, timezone
import csv
import json
import math
from statistics import median
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
from qos_startup_guard import wait_host_ready

METRICS = {'RRU.PrbAvailDl': ('PRB', 'scheduler', 'cell_available_prbs'), 'RRU.PrbAvailUl': ('PRB', 'scheduler', 'cell_available_prbs'), 'RRU.PrbUsedDl': ('PRB', 'scheduler', 'integer_mean_prbs_per_dl_slot'), 'RRU.PrbUsedUl': ('PRB', 'scheduler', 'integer_mean_prbs_per_ul_slot'), 'RRU.PrbTotDl': ('percent', 'scheduler', 'integer_prb_utilization'), 'RRU.PrbTotUl': ('percent', 'scheduler', 'integer_prb_utilization'), 'DRB.RlcSduTransmittedVolumeDL': ('kbit', 'RLC', 'cached_sdu_batch_volume'), 'DRB.RlcSduTransmittedVolumeUL': ('kbit', 'RLC', 'cached_sdu_batch_volume'), 'DRB.UEThpDl': ('kbps', 'RLC', 'provider_mean_throughput'), 'DRB.UEThpUl': ('kbps', 'RLC', 'provider_mean_throughput')}

DOCKER = ["sudo", "docker"]
GNB = "oai-pi-ocudu-zmq-lab-gnb-1"
UE = "oai-pi-ocudu-zmq-lab-nrue-1"
BASE_RIC = "oai-pi-ocudu-zmq-lab-ric-1"
RIC_IMAGE = "limx59/oai-pi-ocudu-flexric-ric:arm64-kpm-csv-metadata-test"
XAPP_IMAGE = "limx59/oai-pi-ocudu-flexric-xapp:arm64-kpm-csv-metadata-test"
GNB_IMAGE = "limx59/oai-pi-ocudu-gnb:arm64-kpm-collection-clock"
SERVER_IMAGE = "limx59/oai-pi-oai-nr-ue:arm64-zmq-test"
TEST_IP = "172.22.0.163"


def command(args, timeout=30):
    result = subprocess.run(
        DOCKER + args, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    if args and args[0] == "logs":
        return result.stdout + result.stderr
    return result.stdout


def inspect(name):
    return json.loads(command(["inspect", name]))[0]


def identity(name):
    value = inspect(name)
    return {
        "id": value["Id"], "image_id": value["Image"],
        "pid": value["State"]["Pid"],
        "started": value["State"]["StartedAt"],
        "restarts": value["RestartCount"],
        "running": value["State"]["Running"],
        "exit_code": value["State"]["ExitCode"],
        "oom_killed": value["State"].get("OOMKilled", False),
        "error": value["State"].get("Error", ""),
    }



def review_statistics(rows):
    """Check exported records; local CSV sequence is not an E2 wire sequence."""
    groups = {}
    seen = set()
    valid = {name: [] for name in METRICS}
    missing = {name: 0 for name in METRICS}
    for row in rows:
        if None in row or None in row.values():
            raise RuntimeError("Malformed CSV row width")
        name = row["measurement"]
        if name not in METRICS:
            raise RuntimeError(f"Unexpected measurement: {name}")
        unit, layer, basis = METRICS[name]
        if (row["unit"], row["source_layer"], row["statistic_basis"]) != (
            unit, layer, basis
        ):
            raise RuntimeError(f"Incorrect metric metadata: {name}")
        group = (
            int(row["report_sequence"]), int(row["gnb_cu_ue_f1ap"]),
            int(row["ue_report_index"]), int(row["row_index"]),
        )
        groups.setdefault(group, []).append(name)
        key = (
            row["node_id"], row["cu_du_id"], row["gnb_cu_ue_f1ap"],
            row["collect_start_ntp64"], row["row_index"], name,
        )
        if key in seen:
            raise RuntimeError(f"Duplicate exported record: {key}")
        seen.add(key)
        if row["incomplete"] not in ("0", "1"):
            raise RuntimeError("Invalid incomplete flag")
        if row["value_type"] == "no_value":
            if row["value"] != "" or row["value_bits_per_second"] != "":
                raise RuntimeError("Unavailable value must remain empty")
            missing[name] += 1
            continue
        if row["value_type"] not in ("integer", "real"):
            raise RuntimeError("Unknown measurement value type")
        value = float(row["value"])
        if not math.isfinite(value) or value < 0:
            raise RuntimeError(f"Invalid numeric value: {name}")
        if name.startswith("RRU.") or unit == "kbit":
            if row["value_type"] != "integer" or not value.is_integer():
                raise RuntimeError(f"Expected integer measurement: {name}")
        if unit == "percent" and value > 100:
            raise RuntimeError(f"PRB utilization outside 0..100: {name}")
        if unit == "kbps":
            converted = float(row["value_bits_per_second"])
            if not math.isfinite(converted) or not math.isclose(
                converted, value * 1000, rel_tol=1e-12, abs_tol=1e-6
            ):
                raise RuntimeError(f"Incorrect throughput conversion: {name}")
        elif row["value_bits_per_second"] != "":
            raise RuntimeError(f"Non-throughput converted to bit/s: {name}")
        if row["incomplete"] == "0":
            valid[name].append(value)

    for key, names in groups.items():
        if len(names) != len(METRICS) or set(names) != set(METRICS):
            raise RuntimeError(f"Missing or repeated metric in report row: {key}")
    for name, values in valid.items():
        if len(values) < 3:
            raise RuntimeError(f"Insufficient complete numeric samples: {name}")
    return {
        "metric_count": len(METRICS),
        "report_rows": len(groups),
        "duplicate_exported_records": 0,
        "metrics": {
            name: {
                "unit": METRICS[name][0],
                "complete_numeric_samples": len(values),
                "no_value_samples": missing[name],
                "minimum": min(values),
                "median": median(values),
                "maximum": max(values),
            }
            for name, values in valid.items()
        },
        "source_batch_identity_exported": False,
        "source_batch_duplicates_validated": False,
        "source_counter_reset_validated": False,
        "pdcp_validated": False,
    }


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ocudu-radio-stats-", dir=parent))
    print(f"Evidence: {dest}", flush=True)
    summary = {
        "passed": False,
        "scope": "Ten DU scheduler PRB and RLC fields, CSV integrity and bounded UL/DL throughput comparison",
        "limitations": "Single UE; nominal windows only; PDCP, source-batch duplication and source-counter reset detection are not validated",
        "comparison_criteria": {"minimum_reports": 5, "ratio_min": 0.70, "ratio_max": 1.50},
        "cleanup_errors": [],
    }
    temporary_ric = None
    probe = None
    server = None
    attached = None
    ran_touched = False
    before_ric = None

    base_files = (
        "deploy/ocudu/compose.zmq.yaml",
        "deploy/ocudu/compose.zmq-worker-test.yaml",
        "deploy/ocudu/compose.e2.yaml",
        "test/ocudu/patches/compose.kpm-collection-clock.yaml",
    )
    compose = ["compose"]
    for filename in base_files:
        compose += ["-f", str(root / filename)]

    try:
        for name in (GNB, UE):
            if inspect(name)["State"]["Running"]:
                raise RuntimeError("Stop the experimental gNB and UE first")
        before_ric = identity(BASE_RIC)
        if not before_ric["running"]:
            raise RuntimeError("Baseline RIC must remain running")
        summary["baseline_ric_before"] = before_ric

        network = json.loads(command([
            "network", "inspect", "docker_open5gs_default",
        ]))[0]
        if any(
            item.get("IPv4Address", "").split("/")[0] == TEST_IP
            for item in network.get("Containers", {}).values()
        ):
            raise RuntimeError("Temporary RIC address is occupied")
        summary["images"] = {
            image: json.loads(command(["image", "inspect", image]))[0]["Id"]
            for image in (RIC_IMAGE, XAPP_IMAGE, GNB_IMAGE, SERVER_IMAGE)
        }

        probe_source = root / "test/ocudu/xapp-radio-stats.py"
        compile(probe_source.read_text(), str(probe_source), "exec")
        (dest / "probe.py").write_text(probe_source.read_text())

        for filename in ("ric.conf", "xapp.conf"):
            text = (root / "deploy/ocudu/config" / filename).read_text()
            if text.count('NearRT_RIC_IP = "172.22.0.162"') != 1:
                raise RuntimeError(f"Unexpected address anchor: {filename}")
            (dest / filename).write_text(text.replace(
                'NearRT_RIC_IP = "172.22.0.162"',
                f'NearRT_RIC_IP = "{TEST_IP}"', 1,
            ))
        text = (root / "deploy/ocudu/config/gnb-zmq-e2.yml").read_text()
        if text.count("  addrs: [172.22.0.162]") != 1:
            raise RuntimeError("Unexpected gNB E2 address anchor")
        (dest / "gnb.yml").write_text(text.replace(
            "  addrs: [172.22.0.162]", f"  addrs: [{TEST_IP}]", 1,
        ))
        override = dest / "compose.test.yaml"
        override.write_text(
            "services:\n  gnb:\n"
            f"    image: {GNB_IMAGE}\n"
            "    environment:\n"
            "      OAI_PI_TEST_REJECT_FIRST_DELETE: \"0\"\n"
            "    volumes:\n"
            f"      - {json.dumps(str(dest / 'gnb.yml') + ':/etc/ocudu/gnb.yml:ro')}\n"
        )

        temporary_ric = command([
            "create", "--pull", "never",
            "--name", "ocudu-rejection-ric-" + uuid.uuid4().hex[:12],
            "--network", "docker_open5gs_default", "--ip", TEST_IP,
            "--ulimit", "core=0",
            "--mount", f"type=bind,src={dest}/ric.conf,"
            "dst=/usr/local/etc/flexric/ric.conf,readonly",
            RIC_IMAGE,
        ]).strip()
        command(["start", temporary_ric])
        time.sleep(2)
        if not inspect(temporary_ric)["State"]["Running"]:
            raise RuntimeError("Temporary RIC exited")

        summary["host_readiness"] = wait_host_ready(
            dest / "host-readiness.json")
        ran_touched = True
        output = command(
            compose + ["-f", str(override), "--profile", "ue",
                       "up", "-d", "--no-deps", "--force-recreate",
                       "--no-build", "--pull", "never", "gnb", "nrue"],
            timeout=90,
        )
        (dest / "ran-start.log").write_text(output)

        deadline = time.monotonic() + 90
        ue_ip = None
        while time.monotonic() < deadline:
            if not inspect(UE)["State"]["Running"]:
                raise RuntimeError("UE exited before its tunnel became ready")
            result = subprocess.run(
                DOCKER + ["exec", UE, "ip", "-j", "-4", "addr",
                          "show", "dev", "oaitun_ue1"],
                capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=10,
            )
            if result.returncode == 0:
                values = json.loads(result.stdout)
                ips = [
                    addr["local"] for item in values
                    for addr in item.get("addr_info", [])
                    if addr.get("family") == "inet"
                ]
                if len(ips) == 1:
                    ue_ip = ips[0]
                    break
            time.sleep(1)
        if not ue_ip:
            raise RuntimeError("UE tunnel readiness timeout")
        summary["ue_ip"] = ue_ip
        ran_before = {name: identity(name) for name in (GNB, UE)}
        ric_before = identity(temporary_ric)

        expected_gnb = json.loads(
            command(["image", "inspect", GNB_IMAGE]))[0]["Id"]
        if inspect(GNB)["Image"] != expected_gnb:
            raise RuntimeError("Unexpected gNB image")

        network = json.loads(command([
            "network", "inspect", "docker_open5gs_default",
        ]))[0]
        if any(
            item.get("IPv4Address", "").split("/")[0] == "172.22.0.151"
            for item in network.get("Containers", {}).values()
        ):
            raise RuntimeError("Traffic endpoint address is occupied")
        if "OAI_PI_TEST_REJECT_FIRST_DELETE=1" in (
            inspect(GNB)["Config"].get("Env") or []
        ):
            raise RuntimeError("Delete-rejection injection must be disabled")

        server = command([
            "create", "--pull", "never",
            "--name", "ocudu-csv-traffic-" + uuid.uuid4().hex[:12],
            "--network", "docker_open5gs_default", "--ip", "172.22.0.151",
            "--cap-add", "NET_ADMIN", "--entrypoint", "/bin/sh", SERVER_IMAGE,
            "-ec",
            "ip route add 192.168.100.0/24 via 172.22.0.8; "
            "exec timeout --signal=INT --kill-after=5s 180s "
            "iperf3 -s -B 172.22.0.151",
        ]).strip()
        command(["start", server])
        time.sleep(1)
        command([
            "exec", UE, "ping", "-I", "oaitun_ue1",
            "-c", "3", "-W", "2", "172.22.0.151",
        ], timeout=15)

        probe = command([
            "create", "--pull", "never",
            "--name", "ocudu-csv-probe-" + uuid.uuid4().hex[:12],
            "--network", "docker_open5gs_default", "--ulimit", "core=0",
            "--mount", f"type=bind,src={dest},dst=/evidence",
            "--mount", f"type=bind,src={dest}/xapp.conf,"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "-e", "OAI_PI_KPM_REPORT_STYLE=4",
            "-e", "KPM_RECORD_SECONDS=40",
            "-e", "XAPP_OUTPUT=/evidence/kpm.csv",
            "-e", "PROBE_OUTPUT=/evidence/probe.json",
            "--entrypoint", "timeout", XAPP_IMAGE,
            "--signal=INT", "--kill-after=5s", "75s",
            "python3", "-u", "/evidence/probe.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ]).strip()
        with (dest / "probe.stdout").open("w") as out, \
             (dest / "probe.stderr").open("w") as err:
            attached = subprocess.Popen(
                DOCKER + ["start", "-a", probe],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if attached.poll() is not None:
                    raise RuntimeError("Recorder exited before readiness")
                if "Recorded metadata report=3 " in (
                    dest / "probe.stdout"
                ).read_text():
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Recorder report readiness timeout")

            summary["directions"] = {}
            for direction in ("uplink", "downlink"):
                started = datetime.now(timezone.utc)
                args = [
                    "exec", UE, "timeout", "--kill-after=5s", "30s",
                    "iperf3", "-c", "172.22.0.151", "-B", ue_ip,
                    "--bind-dev", "oaitun_ue1", "-u", "-b", "1M",
                    "-l", "1200", "-t", "10", "-J", "--get-server-output",
                ]
                if direction == "downlink":
                    args.append("-R")
                raw = command(args, timeout=40)
                finished = datetime.now(timezone.utc)
                (dest / f"iperf-{direction}.json").write_text(raw)
                data = json.loads(raw)
                if "error" in data:
                    raise RuntimeError(data["error"])
                received = data["end"]["sum_received"]
                if not (
                    received["bytes"] > 0
                    and received["bits_per_second"] >= 800000
                    and received["lost_percent"] <= 5
                ):
                    raise RuntimeError(f"{direction}: traffic acceptance failed")
                summary["directions"][direction] = {
                    "started_utc": started.isoformat(),
                    "finished_utc": finished.isoformat(),
                    "receiver": received,
                }
                time.sleep(3)
            attached.wait(timeout=55)
            if attached.returncode:
                raise RuntimeError("Recorder failed; inspect probe logs")

        state = inspect(probe)["State"]
        if state["Running"] or state["ExitCode"]:
            raise RuntimeError("Recorder container did not exit successfully")
        summary["probe"] = json.loads((dest / "probe.json").read_text())
        if not summary["probe"]["passed"]:
            raise RuntimeError("Recorder callback checks failed")

        with (dest / "kpm.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise RuntimeError("Empty CSV")
        summary["statistics"] = review_statistics(rows)
        ue_ids = set()
        for row in rows:
            ue_ids.add(int(row["gnb_cu_ue_f1ap"]))
            if int(row["node_id"]) != 420 or int(row["cu_du_id"]) != 0:
                raise RuntimeError("Unexpected node identity")
            if (int(row["mcc"]), int(row["mnc"])) != (1, 1):
                raise RuntimeError("Unexpected PLMN")
            if (int(row["granularity_ms"]) != 1000
                    or row["measurement"] not in METRICS
                    or row["unit"] != METRICS[row["measurement"]][0]):
                raise RuntimeError("Unexpected granularity or unit")
            first = datetime.fromisoformat(row["nominal_window_start_utc"])
            last = datetime.fromisoformat(row["nominal_window_end_utc"])
            if abs((last - first).total_seconds() - 1) > 0.000001:
                raise RuntimeError("Invalid nominal window duration")
        if len(ue_ids) != 1:
            raise RuntimeError("Expected one stable F1AP UE identity")
        summary["csv"] = {
            "rows": len(rows), "gnb_cu_ue_f1ap": sorted(ue_ids),
            "identity_basis": "KPM gNB-DU UE identity; independent mapping review pending",
            "window_basis": "header plus row granularity; nominal only",
        }

        for direction, item in summary["directions"].items():
            start = datetime.fromisoformat(item["started_utc"]) + timedelta(seconds=2)
            end = datetime.fromisoformat(item["finished_utc"]) - timedelta(seconds=1)
            metric = "DRB.UEThpUl" if direction == "uplink" else "DRB.UEThpDl"
            samples = [
                row for row in rows
                if row["measurement"] == metric
                and row["value_type"] != "no_value"
                and row["incomplete"] == "0"
                and start <= datetime.fromisoformat(row["nominal_window_start_utc"])
                and datetime.fromisoformat(row["nominal_window_end_utc"]) <= end
            ]
            sequences = {row["report_sequence"] for row in samples}
            if len(sequences) < 5:
                raise RuntimeError(f"{direction}: insufficient interior-window reports")
            rates = [float(row["value_bits_per_second"]) for row in samples]
            ratio = median(rates) / item["receiver"]["bits_per_second"]
            item["comparison"] = {
                "reports": len(sequences), "median_kpm_bit_s": median(rates),
                "kpm_to_iperf_ratio": ratio,
                "basis": "nominal interior windows versus whole-run application receiver rate",
            }
            if not 0.70 <= ratio <= 1.50:
                raise RuntimeError(f"{direction}: KPM/iperf ratio outside 0.70..1.50")

        for direction, item in summary["directions"].items():
            name = (
                "DRB.RlcSduTransmittedVolumeUL" if direction == "uplink"
                else "DRB.RlcSduTransmittedVolumeDL"
            )
            start = datetime.fromisoformat(item["started_utc"]) + timedelta(seconds=2)
            end = datetime.fromisoformat(item["finished_utc"]) - timedelta(seconds=1)
            volumes = [
                float(row["value"]) for row in rows
                if row["measurement"] == name
                and row["value_type"] != "no_value"
                and row["incomplete"] == "0"
                and start <= datetime.fromisoformat(row["nominal_window_start_utc"])
                and datetime.fromisoformat(row["nominal_window_end_utc"]) <= end
            ]
            item["rlc_volume"] = {
                "samples": len(volumes),
                "positive_samples": sum(value > 0 for value in volumes),
                "median_kbit": median(volumes) if volumes else None,
                "basis": "cached SDU batch volume; no cumulative-counter differencing",
            }
            if sum(value > 0 for value in volumes) < 5:
                raise RuntimeError(f"{direction}: insufficient positive RLC volume samples")

        stdout = (dest / "probe.stdout").read_text()
        if stdout.count("SUBSCRIPTION DELETE RESPONSE rx") != 1:
            raise RuntimeError("Expected one normal deletion response")
        if "KPM_DELETE_REJECTED" in stdout:
            raise RuntimeError("Unexpected deletion rejection")
        gnb_log = command(["logs", "--timestamps", GNB], timeout=120)
        # Retain runtime identities for independent mapping review.
        identity_lines = [
            line for line in gnb_log.splitlines()
            if "f1ap" in line.lower() or "ue=" in line.lower()
            or "rnti" in line.lower()
        ]
        (dest / "gnb-ue-identity.log").write_text("\n".join(identity_lines) + "\n")
        if identity(temporary_ric) != ric_before:
            raise RuntimeError("Temporary RIC restarted or stopped")
        if {name: identity(name) for name in (GNB, UE)} != ran_before:
            raise RuntimeError("RAN process identity changed during probe")
        summary["passed"] = True
    except Exception as error:
        summary["error"] = str(error)
    finally:
        # Collect diagnostics before stopping or recreating the test RAN.
        if ran_touched:
            try:
                log = command(["logs", "--timestamps", GNB], timeout=120)
                lines = [
                    line for line in log.splitlines()
                    if "[E2" in line or "assert" in line.lower()
                    or "subscription" in line.lower()
                ]
                (dest / "gnb-e2.log").write_text("\n".join(lines) + "\n")
                summary["ran_state_at_cleanup"] = {
                    name: identity(name) for name in (GNB, UE)
                }
            except Exception as error:
                summary.setdefault("diagnostic_errors", []).append(str(error))
        if temporary_ric:
            try:
                summary["test_ric_state_at_cleanup"] = identity(temporary_ric)
            except Exception as error:
                summary.setdefault("diagnostic_errors", []).append(str(error))
        if server:
            try:
                (dest / "traffic-server.log").write_text(
                    command(["logs", "--timestamps", server]))
            except Exception as error:
                summary.setdefault("diagnostic_errors", []).append(str(error))
            try:
                command(["rm", "-f", server])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if probe:
            try:
                command(["rm", "-f", probe])
                if attached is not None:
                    attached.wait(timeout=15)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if ran_touched:
            try:
                command(compose + ["--profile", "ue", "stop", "nrue", "gnb"],
                        timeout=90)
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if temporary_ric:
            try:
                (dest / "ric.log").write_text(
                    command(["logs", "--timestamps", temporary_ric]))
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
            try:
                command(["rm", "-f", temporary_ric])
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if ran_touched:
            try:
                command(compose + [
                    "--profile", "ue", "up", "--no-start", "--no-deps",
                    "--force-recreate", "--no-build", "--pull", "never",
                    "gnb", "nrue",
                ], timeout=90)
                if any(inspect(name)["State"]["Running"] for name in (GNB, UE)):
                    raise RuntimeError("RAN should be stopped after restoration")
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if before_ric is not None:
            try:
                summary["baseline_ric_after"] = identity(BASE_RIC)
                if summary["baseline_ric_after"] != before_ric:
                    raise RuntimeError("Baseline RIC identity changed")
            except Exception as error:
                summary["cleanup_errors"].append(str(error))
        if summary["cleanup_errors"]:
            summary["passed"] = False
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
        print(f"Evidence retained: {dest}", flush=True)
    if not summary["passed"]:
        raise SystemExit(1)
    print("PASS: ten DU statistics fields, CSV integrity and bounded UL/DL comparison.")
    print("Baseline RIC retained; original RAN configuration restored, stopped.")


if __name__ == "__main__":
    main()
