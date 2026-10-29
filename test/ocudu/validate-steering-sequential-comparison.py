#!/usr/bin/env python3
"""Run OAI then OCUDU serially and compare bounded load responses."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from review_oai_steering_load import review as review_oai
from review_steering_load_response import review as review_ocudu


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def baseline(value):
    return {key: value[key] for key in
            ("id", "pid", "started", "restarts", "running")}


def compare(oai_path, ocudu_path):
    reviewed = {}
    summaries = {}
    for label, directory, reviewer in (
        ("oai", oai_path, review_oai),
        ("ocudu", ocudu_path, review_ocudu),
    ):
        summary = json.loads((directory / "summary.json").read_text())
        require(summary["passed"] and not summary["cleanup_errors"],
                f"{label}: child validation failed")
        before = baseline(summary["baseline_ric_before"])
        after = baseline(summary["baseline_ric_after"])
        require(before == after and before["running"],
                f"{label}: baseline RIC changed")
        with (directory / "kpm.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        reviewed[label] = reviewer(rows, summary["probe"], summary["phases"])
        summaries[label] = summary
    require(
        baseline(summaries["oai"]["baseline_ric_after"])
        == baseline(summaries["ocudu"]["baseline_ric_before"]),
        "Baseline RIC changed between systems",
    )
    oai_end = max(
        datetime.fromisoformat(item["finished_utc"])
        for item in summaries["oai"]["phases"].values()
    )
    ocudu_start = min(
        datetime.fromisoformat(item["started_utc"])
        for item in summaries["ocudu"]["phases"].values()
    )
    require(oai_end < ocudu_start, "Expected OAI traffic before OCUDU traffic")
    table = []
    for key in reviewed["oai"]["phases"]:
        a = reviewed["oai"]["phases"][key]
        b = reviewed["ocudu"]["phases"][key]
        oai_phase = summaries["oai"]["phases"][key]
        ocudu_phase = summaries["ocudu"]["phases"][key]
        require(oai_phase["offered_bit_s"] == ocudu_phase["offered_bit_s"],
                "Offered loads differ")
        table.append({
            "phase": key,
            "offered_bit_s": oai_phase["offered_bit_s"],
            "oai_receiver_bit_s": oai_phase["receiver"]["bits_per_second"],
            "ocudu_receiver_bit_s": ocudu_phase["receiver"]["bits_per_second"],
            "oai_kpm_bit_s": a["median_kpm_bit_s"],
            "ocudu_kpm_bit_s": b["median_kpm_bit_s"],
            "oai_kpm_to_iperf_ratio": a["kpm_to_iperf_ratio"],
            "ocudu_kpm_to_iperf_ratio": b["kpm_to_iperf_ratio"],
            "oai_prb_raw_percent": a["median_prb_raw_percent"],
            "ocudu_prb_raw_percent": b["median_prb_utilization_percent"],
        })
    return {
        "passed": True, "order": ["oai", "ocudu"],
        "evidence": {"oai": str(oai_path), "ocudu": str(ocudu_path)},
        "comparison": table,
        "association_basis": {
            "oai": "Receipt-time interior",
            "ocudu": "Interior nominal KPM windows",
        },
        "scope": "Same offered UDP phases; bounded per-system load response",
        "prb_cross_vendor_equivalence_validated": False,
        "capacity_ranking_performed": False,
        "migration_recommended": False,
        "control_executed": False,
    }


def main():
    root = Path(__file__).resolve().parents[2]
    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix="steering-sequential-comparison-", dir=parent,
    ))
    print(f"Evidence: {dest}", flush=True)
    result = {"passed": False, "runs": []}
    paths = {}
    try:
        for label, filename in (
            ("oai", "validate-oai-steering-load.py"),
            ("ocudu", "validate-steering-load-response.py"),
        ):
            print(f"RUNNING: {label}; child output retained in {dest}",
                  flush=True)
            started = datetime.now(timezone.utc)
            log = dest / f"{label}.stdout"
            with log.open("w") as out, (dest / f"{label}.stderr").open("w") as err:
                child = subprocess.run(
                    [sys.executable, "-B", str(root / "test/ocudu" / filename)],
                    cwd=root, stdin=subprocess.DEVNULL,
                    stdout=out, stderr=err, timeout=1200,
                )
            finished = datetime.now(timezone.utc)
            require(child.returncode == 0,
                    f"{label}: validation failed; inspect child logs")
            matches = re.findall(
                r"^Evidence retained: (.+)$", log.read_text(), re.M,
            )
            require(len(matches) == 1, "Expected one child evidence directory")
            paths[label] = Path(matches[0])
            result["runs"].append({
                "system": label, "started_utc": started.isoformat(),
                "finished_utc": finished.isoformat(),
                "evidence": str(paths[label]),
            })
            print(f"PASSED AND CLEANED: {label}", flush=True)
        comparison = compare(paths["oai"], paths["ocudu"])
        result.update(comparison)
        with (dest / "comparison.csv").open("x", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=list(comparison["comparison"][0]),
            )
            writer.writeheader()
            writer.writerows(comparison["comparison"])
    except Exception as error:
        result["passed"] = False
        result["error"] = str(error)
    finally:
        (dest / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
        print(f"Evidence retained: {dest}", flush=True)
    if not result["passed"]:
        raise SystemExit(1)
    print("PASS: sequential OAI/OCUDU bounded load-response comparison.")


if __name__ == "__main__":
    main()
