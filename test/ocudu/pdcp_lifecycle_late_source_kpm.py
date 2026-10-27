"""Validate KPM calculations after live PDCP source reconstruction."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import runpy
import statistics
import time
import uuid

from review_pdcp_late_source import review_late_source


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_post_probe(dest, command, inspect, identity, gnb, ue,
                   xapp_image, lifecycle):
    dest = Path(dest)
    output = dest / "post-reconstruction"
    output.mkdir(exist_ok=False)
    result = {
        "passed": False,
        "scope": "Post-reconstruction traffic and KPM calculation provenance",
        "late_old_source_injection_validated": False,
        "cleanup_errors": [],
    }
    probe = None
    try:
        require(lifecycle["passed"], "Lifecycle reconstruction did not pass")
        for name, previous in lifecycle["before"].items():
            require(identity(name) == previous, "Component identity changed")
        for filename in ("probe.py", "xapp.conf"):
            (output / filename).write_bytes((dest / filename).read_bytes())

        probe = command([
            "create", "--pull", "never",
            "--name", "ocudu-post-reset-" + uuid.uuid4().hex[:12],
            "--network", "docker_open5gs_default", "--ulimit", "core=0",
            "--mount", f"type=bind,src={output},dst=/evidence",
            "--mount", f"type=bind,src={output}/xapp.conf,"
            "dst=/usr/local/etc/flexric/xapp.conf,readonly",
            "-e", "OAI_PI_KPM_REPORT_STYLE=1",
            "-e", "KPM_RECORD_SECONDS=40",
            "-e", "XAPP_OUTPUT=/evidence/kpm.csv",
            "-e", "PROBE_OUTPUT=/evidence/probe.json",
            "--entrypoint", "timeout", xapp_image,
            "--signal=INT", "--kill-after=5s", "75s",
            "python3", "-u", "/evidence/probe.py",
            "-c", "/usr/local/etc/flexric/xapp.conf",
        ]).strip()
        command(["start", probe])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(inspect(probe)["State"]["Running"],
                    "Post-reset recorder exited before readiness")
            log = command(["logs", probe])
            if "Recorded metadata report=3 " in log:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Post-reset recorder readiness timeout")

        # Arm replay only after three post-reset KPM reports were observed.
        command(["exec", gnb, "touch", "/tmp/ocudu-pdcp-late-source.arm"])
        result["late_source_armed_utc"] = datetime.now(timezone.utc).isoformat()

        addresses = json.loads(command([
            "exec", ue, "ip", "-j", "-4", "addr", "show",
            "dev", "oaitun_ue1",
        ]))
        ips = [
            item["local"] for interface in addresses
            for item in interface.get("addr_info", [])
            if item.get("family") == "inet"
        ]
        require(len(ips) == 1, "Expected one post-reset UE IPv4 address")
        result["ue_ip"] = ips[0]
        result["directions"] = {}

        for direction in ("uplink", "downlink"):
            started = datetime.now(timezone.utc)
            args = [
                "exec", ue, "timeout", "--kill-after=5s", "30s",
                "iperf3", "-c", "172.22.0.151", "-B", ips[0],
                "--bind-dev", "oaitun_ue1", "-u", "-b", "1M",
                "-l", "1200", "-t", "10", "-J", "--get-server-output",
            ]
            if direction == "downlink":
                args.append("-R")
            raw = command(args, timeout=40)
            finished = datetime.now(timezone.utc)
            (output / f"iperf-{direction}.json").write_text(raw)
            data = json.loads(raw)
            require("error" not in data, "Post-reset iperf error")
            received = data["end"]["sum_received"]
            require(
                received["bytes"] > 0
                and received["bits_per_second"] >= 800000
                and received["lost_percent"] <= 5,
                f"Post-reset {direction} traffic acceptance failed",
            )
            result["directions"][direction] = {
                "started_utc": started.isoformat(),
                "finished_utc": finished.isoformat(),
                "receiver": received,
            }
            time.sleep(3)

        require(command(["wait", probe], timeout=55).strip() == "0",
                "Post-reset recorder failed")
        state = inspect(probe)["State"]
        require(not state["Running"] and state["ExitCode"] == 0,
                "Post-reset recorder did not exit successfully")
        recorder = json.loads((output / "probe.json").read_text())
        require(recorder.get("passed") is True
                and not recorder.get("cleanup_errors"),
                "Post-reset recorder checks failed")
        result["probe"] = recorder

        with (output / "kpm.csv").open(newline="") as stream:
            post_rows = list(csv.DictReader(stream))
        require(len(post_rows) >= 30, "Insufficient post-reset CSV reports")
        with (dest / "pre-release-kpm.csv").open(newline="") as stream:
            baseline_rows = list(csv.DictReader(stream))

        full_log = command(["logs", "--timestamps", gnb], timeout=30)
        trace = "\n".join(
            line for line in full_log.splitlines()
            if any(token + " " in line for token in (
                "PDCP_SOURCE_ID", "PDCP_BATCH_INPUT",
                "PDCP_LATE_SOURCE_FAULT", "PDCP_KPM_SOURCE", "PDCP_KPM_RESULT",
            ))
        ) + "\n"
        (output / "late-source-trace.log").write_text(trace)
        late_review = review_late_source(trace, lifecycle, post_rows)
        (output / "late-source-review.json").write_text(
            json.dumps(late_review, indent=2) + "\n")
        result["late_old_source"] = late_review
        result["late_old_source_injection_validated"] = True
        provenance = "\n".join(
            line for line in full_log.splitlines()
            if any(token + " " in line for token in (
                "PDCP_BATCH_INPUT", "PDCP_KPM_SOURCE", "PDCP_KPM_RESULT",
            ))
        ) + "\n"
        (output / "combined-provenance.log").write_text(provenance)
        reviewer = runpy.run_path(str(
            Path(__file__).with_name("review-pdcp-provenance-late-source.py")
        ))["review"]
        reviewed = reviewer(provenance, baseline_rows + post_rows)
        require(reviewed["epoch_resets_checked"] == 1,
                "Expected exactly one source epoch reset")

        admissions = {}
        for line in provenance.splitlines():
            if "PDCP_BATCH_INPUT " in line:
                fields = dict(re.findall(r"(\w+)=([^\s]+)", line))
                if fields["accepted"] == "true":
                    admissions[int(fields["revision"])] = fields

        post_mappings = reviewed["mappings"][len(baseline_rows):]
        references = 0
        expected_key = tuple(lifecycle["source_key"])
        for mapping in post_mappings:
            for revision in mapping["revisions"]:
                fields = admissions[revision]
                require(
                    (int(fields["ue"]), fields["rb"]) == expected_key
                    and int(fields["epoch"]) == lifecycle["new_epoch"],
                    "Post-reset calculation included an unexpected source epoch",
                )
                references += 1
        require(references >= 30, "Insufficient new-epoch calculation sources")

        ul = result["directions"]["uplink"]
        start = datetime.fromisoformat(ul["started_utc"])
        finish = datetime.fromisoformat(ul["finished_utc"])
        numeric = []
        for row in post_rows:
            first = datetime.fromisoformat(row["nominal_window_start_utc"])
            last = datetime.fromisoformat(row["nominal_window_end_utc"])
            if (first - start).total_seconds() >= 1 and (
                finish - last
            ).total_seconds() >= 1:
                if row["value_type"] == "integer":
                    numeric.append(int(row["value"]))
        require(len(numeric) >= 5, "Insufficient post-reset uplink metrics")
        require(statistics.median(numeric) >= 95,
                "Post-reset uplink packet-success criterion failed")

        for name, previous in lifecycle["before"].items():
            require(identity(name) == previous,
                    "Component identity changed during post-reset recording")
        (output / "provenance-review.json").write_text(
            json.dumps(reviewed, indent=2) + "\n")
        result.update({
            "passed": True,
            "post_reset_kpm_calculation_validated": True,
            "post_reset_csv_rows": len(post_rows),
            "new_epoch_source_references_checked": references,
            "ul_interior_numeric_reports": len(numeric),
            "ul_median_success_percent": statistics.median(numeric),
            "provenance_review": {
                key: value for key, value in reviewed.items()
                if key != "mappings"
            },
            "component_identities_unchanged": True,
        })
    except Exception as error:
        result["error"] = str(error)
    finally:
        if probe is not None:
            try:
                (output / "probe.log").write_text(
                    command(["logs", "--timestamps", probe]))
            except Exception as error:
                result["diagnostic_error"] = str(error)
            try:
                command(["rm", "-f", probe])
            except Exception as error:
                result["cleanup_errors"].append(str(error))
                result["passed"] = False
        (output / "summary.json").write_text(
            json.dumps(result, indent=2) + "\n")
    require(result["passed"],
            result.get("error", "Post-reset recorder cleanup failed"))
    return result
