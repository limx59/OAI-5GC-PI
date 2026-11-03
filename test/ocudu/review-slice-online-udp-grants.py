#!/usr/bin/env python3
"""Review timed UDP results, receive drain and per-slot UL grants."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "test/ocudu/.local/evidence"

HEADER = re.compile(
    r"^.*Slot decisions pci=1 .*?\(\d+ PDSCHs?, (\d+) PUSCHs?.*$",
    re.M,
)
GRANT = re.compile(
    r"UE PUSCH: ue=(\d+) c-rnti=(0x[0-9a-fA-F]+)"
    r".*?\brb=\[(\d+)\.\.(\d+)\).*?\bnrtx=(\d+)\b"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def review(dest):
    dest = dest.resolve()
    require(dest.is_relative_to(BASE.resolve()) and dest.is_dir(),
            "Evidence outside repository evidence directory")

    def read(name):
        path = dest / name
        require(path.resolve().is_relative_to(dest) and path.is_file(),
                "Missing or unexpected evidence: " + name)
        return path.read_text(errors="strict")

    summary = json.loads(read("summary.json"))
    require(summary.get("passed") is True
            and summary.get("transport") == "UDP"
            and summary.get("server_grace_seconds") == 180
            and summary.get("control_requests_sent") == 2
            and summary.get("cleanup_errors") == [],
            "Unexpected original UDP test result")

    require(summary.get("baseline_before")
            and summary["baseline_before"] == summary.get("baseline_after"),
            "Baseline process identities changed or missing")
    require(summary.get("test_before")
            and summary["test_before"] == summary.get("test_after"),
            "Test process identities changed or missing")
    require(summary["test_before"].get("traffic", {}).get("image") ==
            "sha256:6146f02626b1a5157552ed9be9afdfc92a2746fb5c33b38051c8aa80172a9904",
            "Unexpected traffic image")
    phases = summary.get("phases", [])
    require(len(phases) == 2
            and [item.get("name") for item in phases] == ["limited", "restored"]
            and [item.get("max_ratio") for item in phases] == [20, 100]
            and all(item.get("response_validated") is True
                    and item.get("scheduler_event_validated") is True
                    and item.get("pings_passed") == 5 for item in phases),
            "Incomplete control, execution or connectivity evidence")

    results = {}
    for phase in ("baseline", "limited", "restored"):
        data = json.loads(read(f"iperf-ul-{phase}.json"))
        server = data.get("server_output_json")
        require(isinstance(server, dict)
                and not data.get("error") and not server.get("error"),
                "Incomplete UDP results: " + phase)
        parameters = data.get("start", {}).get("test_start", {})
        require(parameters.get("protocol") == "UDP"
                and parameters.get("duration") == 6
                and parameters.get("target_bitrate") == 10000000
                and parameters.get("blksize") == 1200
                and parameters.get("num_streams") == 1
                and parameters.get("reverse") == 0,
                "Unexpected UDP workload: " + phase)
        sent = data.get("end", {}).get("sum_sent", {})
        received = server.get("end", {}).get("sum_received", {})
        echoed = data.get("end", {}).get("sum_received", {})
        require(sent.get("sender") is True
                and received.get("sender") is False
                and received.get("bytes", 0) >= 65536
                and sent.get("bytes") == received.get("bytes") == echoed.get("bytes")
                and received.get("bits_per_second", 0) > 0
                and received.get("lost_packets") == 0,
                "UDP final byte counts or packet loss require review: " + phase)

        streams_before = json.loads(read(f"traffic.{phase}.before-load.streams.json"))
        streams_after = json.loads(read(f"traffic.{phase}.after-load.streams.json"))
        require(set(streams_before) == set(streams_after) == {"stdout", "stderr"}
                and all(isinstance(streams_before[key], str)
                        and isinstance(streams_after[key], str)
                        and streams_after[key].startswith(streams_before[key])
                        for key in ("stdout", "stderr")),
                "Traffic stream history mismatch: " + phase)
        delta = "\n".join(
            streams_after[key][len(streams_before[key]):]
            for key in ("stdout", "stderr")
        )
        require(delta.count("LAB_IPERF_SERVER_GRACE seconds=180") == 1,
                "Server grace evidence missing or duplicated: " + phase)
        drains = re.findall(
            r"LAB_IPERF_UDP_DRAIN before=(\d+) after=(\d+) "
            r"polls=(\d+) quiet_reached=(\d+)", delta,
        )
        require(len(drains) == 1, "UDP drain evidence missing or duplicated: " + phase)
        initial, final, polls, quiet = map(int, drains[0])
        require(initial <= final == received["bytes"]
                and 50 <= polls <= 500 and quiet == 1,
                "UDP receive drain evidence invalid: " + phase)

        before = read(f"gnb.ul-{phase}.before-load.log")
        after = read(f"gnb.ul-{phase}.after-load.log")
        require(after.startswith(before), "Log history mismatch: " + phase)

        headers = list(HEADER.finditer(after))
        widths = Counter()
        totals = []
        checked = 0

        for index, match in enumerate(headers):
            if match.start() < len(before):
                continue
            end = (headers[index + 1].start()
                   if index + 1 < len(headers) else len(after))
            block = after[match.end():end]
            records = GRANT.findall(block)
            require(len(records) == int(match.group(1))
                    and block.count("UE PUSCH:") == len(records),
                    "Incomplete PUSCH parsing: " + phase)
            checked += 1
            total = 0
            for ue, rnti, low, high, nrtx in records:
                low, high = int(low), int(high)
                require(ue == "0" and int(rnti, 16) == 0x4601,
                        "Unexpected UE identity: " + phase)
                require(0 <= low < high <= 51,
                        "Unexpected RB range: " + phase)
                require(int(nrtx) == 0,
                        "Retransmission requires separate review: " + phase)
                width = high - low
                widths[width] += 1
                total += width
            require(total <= 51, "UL allocation exceeds cell size")
            if records:
                totals.append(total)

        require(checked > 0 and totals, "Missing UL grants: " + phase)
        if phase == "limited":
            require(max(totals) <= 10,
                    "Observed UL per-slot allocation exceeds configured cap")
            require(10 in totals, "Limited phase did not reach configured cap")
        else:
            require(max(totals) > 10,
                    phase + " phase did not exceed the limited cap")

        results[phase] = {
            "checked_slot_headers": checked,
            "pusch_grants": sum(widths.values()),
            "active_ul_slots": len(totals),
            "max_prbs_per_logged_ul_slot": max(totals),
            "slots_above_limited_cap": sum(value > 10 for value in totals),
            "slots_at_limited_cap": totals.count(10),
            "grant_width_histogram": dict(sorted(widths.items())),
            "all_grants_new_transmissions": True,
        }

    return {
        "passed": True,
        "scope": "Retained timed UDP results, receive drain and UL per-slot cap/restoration",
        "cell_prbs": 51,
        "limited_max_ratio": 20,
        "limited_prb_cap": 10,
        "phases": results,
        "ul_cap_effect_validated": True,
        "timed_udp_completed": True,
        "general_iperf3_fix_validated": False,
        "multi_agent_control_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    result = review(args.evidence)
    output = args.evidence.resolve() / "online-udp-grant-review.json"
    text = json.dumps(result, indent=2) + "\n"
    with output.open("x") as stream:
        stream.write(text)
    print(text, end="")
    print("SAVED:", output)


if __name__ == "__main__":
    main()
