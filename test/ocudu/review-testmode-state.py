#!/usr/bin/env python3
"""Review parsed testmode states and linked retained normal-UE evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"
EXPECTED = {
    "default": (False, 0, False, False),
    "explicit-disabled": (False, 0, False, False),
    "du-enabled": (True, 17921, False, True),
    "cu-up-disabled": (False, 0, False, False),
    "cu-up-enabled": (False, 0, True, False),
    "both-enabled": (True, 17921, True, True),
    "retained-real-ue": (False, 0, False, False),
}
MARKER = re.compile(
    r"^LAB_TESTMODE_STATE du_enabled=(true|false) du_rnti=(\d+) "
    r"cu_up_enabled=(true|false) no_core=(true|false)$", re.M,
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    dest = dest.resolve()
    require(dest.is_relative_to(BASE.resolve()) and dest.is_dir(),
            "Unexpected evidence directory")

    def read(directory, name):
        path = directory / name
        require(path.resolve().is_relative_to(BASE.resolve()) and path.is_file(),
                "Missing or unexpected evidence: " + name)
        return path.read_text()

    summary = json.loads(read(dest, "summary.json"))
    require(summary.get("passed") is True
            and summary.get("cleanup_errors") == [],
            "Original state-check run failed")
    before = summary.get("baseline_before")
    require(isinstance(before, dict) and before == summary.get("baseline_after"),
            "Baseline process identities changed")
    require(set(summary["cases"]) == set(EXPECTED), "Unexpected case set")
    for name, expected in EXPECTED.items():
        directory = dest / name
        result = summary["cases"][name]
        state = json.loads(read(directory, "container.json"))
        require(state["image"] == summary["image"]["id"]
                and state["exit_code"] == 0
                and state["oom_killed"] is False
                and state["restarts"] == 0,
                "Unexpected container outcome")
        raw_config = read(directory, "gnb.yml").encode()
        require(hashlib.sha256(raw_config).hexdigest()
                == result["configuration_sha256"],
                "Configuration hash mismatch")
        logs = "\n".join(read(directory, name)
                         for name in ("stdout.log", "stderr.log"))
        markers = MARKER.findall(logs)
        require(len(markers) == 1
                and logs.count("LAB_CONFIG_VALIDATION_PASSED") == 1,
                "Invalid validation/state markers")
        du, rnti, cu_up, no_core = markers[0]
        actual = (du == "true", int(rnti), cu_up == "true", no_core == "true")
        recorded = tuple(result[key] for key in (
            "du_enabled", "du_rnti", "cu_up_enabled", "no_core",
        ))
        require(result["passed"] is True and actual == recorded == expected,
                "Parsed testmode state mismatch")

    link = summary["retained_real_ue"]
    historical = (BASE / link["evidence"]).resolve()
    require(historical.is_relative_to(BASE.resolve()) and historical.is_dir(),
            "Unexpected historical evidence directory")
    old = json.loads(read(historical, "summary.json"))
    require(old.get("passed") is True and old.get("cleanup_errors") == [],
            "Historical UE run failed")
    retained = read(historical, "config/gnb.yml").encode()
    replayed = read(dest / "retained-real-ue", "gnb.yml").encode()
    digest = hashlib.sha256(retained).hexdigest()
    require(retained == replayed
            and digest == old["configuration"]["generated_sha256"]
            == link["configuration_sha256"]
            == summary["cases"]["retained-real-ue"]["configuration_sha256"],
            "Historical configuration linkage mismatch")
    require(link["ue_address"] == old["ue_address"],
            "Historical UE address mismatch")

    for name in (
        "ping-before-control.log", "ping-limited.log", "ping-restored.log",
    ):
        ping = read(historical, name)
        require(re.search(r"5 packets transmitted,\s*5 (?:packets )?received", ping)
                and re.search(r"(?:^|,\s)0% packet loss", ping),
                "Historical UPF ping evidence failed")

    gnb = read(historical, "gnb.final.log")
    ue = read(historical, "nrue.final.log")
    require(re.search(r"NG Setup|NGSetup|NG setup", gnb, re.I)
            and re.search(r"RRCSetupComplete|RRC Setup Complete|RRC setup complete",
                          ue, re.I)
            and re.search(r"Registration (?:accept|complete)", ue, re.I)
            and re.search(r"PDU.?Session.*(?:establish|accept)", ue, re.I),
            "Historical access protocol evidence missing")
    flags = re.findall(r'["\']?test_mode["\']?\s*[:=]\s*(true|false)\b',
                       gnb, re.I)
    require(flags and all(value.lower() == "false" for value in flags),
            "Historical testmode log flags require review")
    return {
        "passed": True,
        "parsed_state_cases": len(EXPECTED),
        "historical_configuration_sha256": digest,
        "historical_normal_ue_path_supported": True,
        "historical_testmode_false_log_fields": len(flags),
        "historical_process_memory_inspected": False,
        "live_test_ue_creation_validated": False,
        "scope": "Parsed-state matrix and retained normal-UE evidence linkage",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.evidence), indent=2))
    print("Read-only review; original evidence unchanged.")


if __name__ == "__main__":
    main()
