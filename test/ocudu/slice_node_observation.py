#!/usr/bin/env python3
"""Extract grant-conditioned post-allocation DL queue observations.

Receipt times describe host log queries, not source collection times.
Missing grants do not establish an empty queue or an idle node.
No conversion to PRB demand percentages is performed.
"""
import hashlib
import math
import re

GRANT = re.compile(
    r"UE PDSCH: ue=(\d+) c-rnti=(0x[0-9a-fA-F]+)"
    r".*?\brb=\[(\d+)\.\.(\d+)\)"
    r".*?\bnrtx=(\d+)\b.*?\bdl_bo=(\d+)\b"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value))


def observe(node, source_instance, revision, before, after,
            query_start_s, query_end_s):
    require(node in ("420", "421"), "Unexpected node identity")
    require(isinstance(source_instance, str) and source_instance,
            "Missing source instance")
    require(type(revision) is int and revision > 0,
            "Invalid report revision")
    require(finite(query_start_s) and finite(query_end_s)
            and 0 <= query_start_s < query_end_s,
            "Invalid host query interval")
    require(isinstance(before, dict) and isinstance(after, dict)
            and set(before) == set(after) == {"stdout", "stderr"},
            "Unexpected log streams")

    samples = []
    provenance = {}
    for stream in ("stdout", "stderr"):
        previous, current = before[stream], after[stream]
        require(isinstance(previous, str) and isinstance(current, str)
                and current.startswith(previous),
                "Source log history changed")
        require(not previous or previous.endswith("\n"),
                "Previous snapshot ends in a partial line")
        delta = current[len(previous):]
        require(not delta or delta.endswith("\n"),
                "Current snapshot ends in a partial line")
        provenance[stream] = {
            "previous_characters": len(previous),
            "current_characters": len(current),
            "delta_sha256": hashlib.sha256(delta.encode()).hexdigest(),
        }
        for offset, line in enumerate(delta.splitlines()):
            if "UE PDSCH:" not in line:
                continue
            match = GRANT.search(line)
            require(match is not None, "Unparsed DL queue observation")
            ue, rnti, low, high, nrtx, queue = match.groups()
            low, high, queue = int(low), int(high), int(queue)
            require(ue == "0" and rnti.lower() == "0x4601",
                    "Unexpected UE identity")
            require(nrtx == "0", "Retransmission requires separate observation")
            require(0 <= low < high <= 51, "Unexpected DL RB range")
            lcids = re.findall(r"\blcid=(\d+):", line)
            require(lcids and set(lcids) == {"4"},
                    "Unexpected or unclassified logical channel")
            samples.append({
                "stream": stream,
                "delta_line_index": offset,
                "ue": 0,
                "rnti": rnti.lower(),
                "prb_width": high - low,
                "pending_dl_bytes_after_grant": queue,
            })

    queues = [item["pending_dl_bytes_after_grant"] for item in samples]
    return {
        "node_id": node,
        "source_instance": source_instance,
        "revision": revision,
        "host_query_start_s": query_start_s,
        "host_query_end_s": query_end_s,
        "source_collection_time_validated": False,
        "scope": "Single-UE LCID 4 new-transmission grant-conditioned queue samples",
        "queue_unit": "bytes",
        "queue_sampling_point": "after PDSCH transport-block construction",
        "observation_status": "observed" if samples else "unknown",
        "sample_count": len(samples),
        "queue_statistics": {
            "minimum": min(queues),
            "maximum": max(queues),
            "positive_samples": sum(value > 0 for value in queues),
        } if queues else None,
        "samples": samples,
        "provenance": provenance,
        "prb_demand_percent_established": False,
        "control_requests_sent": 0,
    }
