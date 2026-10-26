#!/usr/bin/env python3
"""Repeat PDCP batch-history integration and provenance checks serially."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

CASES = ("validate-pdcp-batch-history.py",)


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=3)
    args = parser.parse_args()

    tests = Path(__file__).resolve().parent
    for name in CASES:
        if not (tests / name).is_file():
            parser.error(f"Missing validator: {name}")

    sources = {
        name: tests / name
        for name in (
            *CASES, "review-pdcp-provenance.py", "xapp-pdcp-stats.py",
            "qos_startup_guard.py", "config/gnb-zmq-pdcp.yml",
            "patches/pdcp-batch-history.h",
            "patches/patch-ocudu-pdcp-batch-history.py",
        )
    }
    for name, source in sources.items():
        if not source.is_file():
            parser.error(f"Missing prerequisite: {name}")

    parent = Path.home() / "Work/oai-test-evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(
        prefix="ocudu-pdcp-batch-regression-", dir=parent))
    summary = {
        "passed": False,
        "started_utc": utc(),
        "rounds": args.rounds,
        "scope": "Repeated PDCP batch-history delivery, clocks and provenance checks",
        "limitations": (
            "Retains individual case limits; not long-term stability, "
            "protocol query-ID correlation, live source faults or lifecycle reset validation"
        ),
        "runs": [],
        "source_sha256": {
            name: digest(source) for name, source in sources.items()
        },
    }
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    def save():
        temporary = dest / "summary.json.tmp"
        temporary.write_text(json.dumps(summary, indent=2) + "\n")
        temporary.replace(dest / "summary.json")

    def verify_sources():
        for name, source in sources.items():
            if digest(source) != summary["source_sha256"][name]:
                raise RuntimeError(f"Source changed during regression: {name}")

    print(f"Regression evidence: {dest}", flush=True)
    save()
    try:
        for number in range(1, args.rounds + 1):
            for name in CASES:
                verify_sources()
                print(f"\n=== Round {number}/{args.rounds}: {name} ===",
                      flush=True)
                log = dest / f"round-{number}-{Path(name).stem}.log"
                item = {
                    "round": number, "case": name,
                    "started_utc": utc(), "log": str(log), "passed": False,
                }
                summary["runs"].append(item)
                save()

                # Child validators own container cleanup. No outer timeout
                # interrupts their finally blocks.
                with log.open("x") as stream:
                    result = subprocess.run(
                        [sys.executable, "-B", "-u", str(tests / name)],
                        stdin=subprocess.DEVNULL,
                        stdout=stream, stderr=subprocess.STDOUT,
                        env=env,
                    )
                item["exit_code"] = result.returncode
                item["finished_utc"] = utc()
                save()

                matches = re.findall(
                    r"^Evidence: (.+)$", log.read_text(), re.M)
                if len(matches) != 1:
                    raise RuntimeError(
                        f"Cannot identify case evidence; inspect {log}")
                evidence = Path(matches[0])
                item["evidence"] = str(evidence)
                case_summary = json.loads(
                    (evidence / "summary.json").read_text())
                item["passed"] = (
                    result.returncode == 0
                    and case_summary.get("passed") is True
                    and not case_summary.get("cleanup_errors")
                )
                verify_sources()
                save()
                print(f"Passed: {item['passed']}; evidence: {evidence}",
                      flush=True)
                if not item["passed"]:
                    raise RuntimeError(
                        f"Regression stopped after failure; inspect {log}")

        summary["passed"] = True
    except KeyboardInterrupt:
        summary["error"] = (
            "Interrupted; review child evidence and container cleanup "
            "before another run"
        )
    except Exception as error:
        summary["error"] = str(error)
    finally:
        summary["finished_utc"] = utc()
        save()
        print(json.dumps(summary, indent=2), flush=True)
        print(f"Regression evidence retained: {dest}", flush=True)

    if not summary["passed"]:
        raise SystemExit(1)
    print(f"PASS: all {args.rounds * len(CASES)} PDCP batch-history regression runs completed.")


if __name__ == "__main__":
    main()
