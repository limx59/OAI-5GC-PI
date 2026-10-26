#!/usr/bin/env python3
"""Review retained PDCP provenance without starting containers."""

import argparse
from collections import Counter, defaultdict, deque
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "Timestamp lacks timezone")
    return result



def application_stamp(prefix):
    docker_time = stamp(prefix[0])
    application_time = datetime.fromisoformat(prefix[1])
    if application_time.tzinfo is None:
        application_time = application_time.replace(tzinfo=timezone.utc)
    require(
        abs((docker_time - application_time).total_seconds()) <= 5,
        "Application UTC interpretation differs from Docker time by over 5 seconds",
    )
    return application_time


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def percentage(sdus, pdus):
    return int(f32(f32(f32(sdus) / f32(pdus)) * 100))


def review(log, rows):
    inputs = {}
    histories = defaultdict(lambda: deque(maxlen=10))
    sources = defaultdict(list)
    results = {}
    input_statuses = Counter()
    uses = Counter()
    expired_total = 0
    no_value_reasons = Counter()

    for line in log.splitlines():
        match = re.search(
            r"\b(PDCP_BATCH_INPUT|PDCP_KPM_SOURCE|PDCP_KPM_RESULT)\b", line)
        if not match:
            continue
        # Prefer the application's timestamp over Docker's collection time.
        prefix = line[:match.start()].split()
        require(len(prefix) >= 2, "Missing application timestamp")
        when = application_stamp(prefix)
        fields = dict(re.findall(r"(\w+)=([^\s]+)", line[match.end():]))
        kind = match.group(1)

        if kind == "PDCP_BATCH_INPUT":
            status = int(fields["status"])
            input_statuses[status] += 1
            require(fields["accepted"] in ("true", "false"), "Invalid admission")
            if fields["accepted"] == "false":
                require(status in (2, 3, 4, 5), "Invalid rejection status")
                continue
            require(status in (0, 1), "Invalid accepted status")
            require(fields["tx"] == fields["rx"], "Accepted mismatched counters")
            revision = int(fields["revision"])
            require(revision not in inputs, "Duplicate accepted revision")
            item = {
                "ue": int(fields["ue"]), "rb": fields["rb"],
                "counter": int(fields["rx"]), "epoch": int(fields["epoch"]),
                "sdus": int(fields["rx_sdus"]), "pdus": int(fields["rx_pdus"]),
                "stamp": when, "revision": revision,
            }
            inputs[revision] = item
            histories[(item["ue"], item["rb"])].append(item)
            continue

        query = int(fields["query"])
        require(query not in results, "Evidence follows a completed query")
        if kind == "PDCP_KPM_SOURCE":
            revision = int(fields["revision"])
            require(revision in inputs, "Source revision has no accepted input")
            original = inputs[revision]
            for field, value in (
                ("ue", original["ue"]), ("counter", original["counter"]),
                ("epoch", original["epoch"]), ("rx_sdus", original["sdus"]),
                ("rx_pdus", original["pdus"]),
            ):
                require(int(fields[field]) == value, f"Source/input mismatch: {field}")
            require(fields["rb"] == original["rb"], "Bearer mismatch")
            age = int(fields["age_ms"])
            require(0 <= age < 2500, "Expired source included")
            inferred_age = (when - original["stamp"]).total_seconds() * 1000
            require(abs(inferred_age - age) <= 50,
                    "Logged receipt age differs from application timestamps")
            require(revision not in sources[query], "Batch counted twice in query")
            sources[query].append(revision)
            uses[revision] += 1
            continue

        revisions = sources[query]
        require(len(revisions) == int(fields["batches"]), "Batch count mismatch")
        sdus = sum(inputs[r]["sdus"] for r in revisions)
        pdus = sum(inputs[r]["pdus"] for r in revisions)
        require(sdus == int(fields["rx_sdus"]), "SDU sum mismatch")
        require(pdus == int(fields["rx_pdus"]), "PDU sum mismatch")

        # Independently reconstruct the retained per-source capacity and age
        # selection. Fail if wall-clock logging lies too close to the boundary.
        eligible = []
        expired = 0
        for history in histories.values():
            for item in history:
                age = (when - item["stamp"]).total_seconds() * 1000
                require(age >= -50, "Input timestamp is later than query")
                require(abs(age - 2500) > 50,
                        "Age boundary ambiguous from wall-clock logs")
                if age < 2500:
                    eligible.append(item["revision"])
                else:
                    expired += 1
        require(set(eligible) == set(revisions), "Fresh cache selection mismatch")
        require(expired == int(fields["expired"]), "Expired cache count mismatch")
        expired_total += expired

        expected = "no_value" if not revisions or pdus == 0 else str(percentage(sdus, pdus))
        require(fields["value"] == expected, "Calculated percentage mismatch")
        if expected == "no_value":
            no_value_reasons["empty_history" if not revisions else "zero_denominator"] += 1
        results[query] = {
            "query": query, "stamp": when, "value": expected,
            "revisions": list(revisions), "rx_sdus": sdus, "rx_pdus": pdus,
        }

    require(len(results) >= 30, "Insufficient calculation evidence")
    require(sorted(results) == list(range(1, len(results) + 1)),
            "Missing or nonconsecutive query IDs")
    require(set(sources).issubset(results), "Source lines without result")
    require(len(rows) == len(results), "CSV/query count mismatch")

    mappings = []
    matched = set()
    for row in rows:
        require(row["incomplete"] == "0", "Incomplete CSV report")
        require(row["measurement"] == "DRB.PacketSuccessRateUlgNBUu",
                "Unexpected CSV metric")
        end = stamp(row["nominal_window_end_utc"])
        received = stamp(row["received_at_utc"])
        candidates = [
            item for item in results.values()
            if abs((item["stamp"] - end).total_seconds()) <= 0.1
            and -0.01 <= (received - item["stamp"]).total_seconds() <= 0.5
        ]
        require(len(candidates) == 1, "CSV/query timing association is ambiguous")
        item = candidates[0]
        require(item["query"] not in matched, "Query matched to multiple CSV rows")
        matched.add(item["query"])
        if item["value"] == "no_value":
            require(row["value_type"] == "no_value" and row["value"] == "",
                    "CSV unavailable value mismatch")
        else:
            require(row["value_type"] == "integer", "CSV value type mismatch")
            require(int(row["value"]) == int(item["value"]), "CSV value mismatch")
        mappings.append({
            "report_sequence": int(row["report_sequence"]),
            "query": item["query"], "revisions": item["revisions"],
            "value": item["value"],
            "query_to_receive_s": (received - item["stamp"]).total_seconds(),
        })
    require(len(matched) == len(results), "Unmatched calculation results")

    return {
        "passed": True,
        "accepted_inputs": len(inputs),
        "input_status_counts": dict(input_statuses),
        "calculations_checked": len(results),
        "source_references_checked": sum(uses.values()),
        "expired_cache_entries_excluded_across_queries": expired_total,
        "revisions_reused_across_queries": sum(count > 1 for count in uses.values()),
        "no_value_reasons": dict(no_value_reasons),
        "csv_rows_matched": len(mappings),
        "association_basis": (
            "Unique single-subscription timestamp association "
            "(nominal end +/-100 ms; receipt -10..500 ms) and exact value"
        ),
        "receipt_age_crosscheck_tolerance_ms": 50,
        "application_timestamp_basis": "UTC, checked against each Docker timestamp within 5 seconds",
        "protocol_query_id_exported": False,
        "live_source_fault_injection_validated": False,
        "source_lifecycle_reset_validated": False,
        "mappings": mappings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (args.evidence / "provenance-review.json")
    if output.exists():
        parser.error(f"Review already exists: {output}")

    result = {"passed": False}
    try:
        with (args.evidence / "kpm.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        result = review(
            (args.evidence / "pdcp-provenance.log").read_text(), rows)
    except Exception as error:
        result["error"] = str(error)
    result["reviewed_utc"] = datetime.now(timezone.utc).isoformat()
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(
        {k: v for k, v in result.items() if k != "mappings"}, indent=2))
    print(f"Saved: {output}")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
