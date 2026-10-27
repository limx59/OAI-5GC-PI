"""Independently check one late old-source replay and its rejection."""

from datetime import datetime, timezone
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def application_time(line):
    value = datetime.fromisoformat(line.split()[1].replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def review_late_source(log, lifecycle, rows):
    records, faults, query_times = [], [], []
    pending = None
    for line in log.splitlines():
        fields = dict(re.findall(r"(\w+)=([^\s]+)", line))
        if "PDCP_SOURCE_ID " in line:
            require(pending is None, "Source identity lacks admission")
            pending = fields
        elif "PDCP_BATCH_INPUT " in line:
            require(pending is not None, "Admission lacks source identity")
            require(all(fields[k] == pending[k] for k in ("ue", "rb", "tx", "rx")),
                    "Source/admission mismatch")
            records.append(dict(
                fields, instance=pending["instance"], time=application_time(line)))
            pending = None
        elif "PDCP_LATE_SOURCE_FAULT " in line:
            faults.append((fields, application_time(line), len(records)))
        elif "PDCP_KPM_RESULT " in line:
            query_times.append(application_time(line))

    require(len(faults) == log.count("PDCP_LATE_SOURCE_FAULT ") == 1,
            "Expected exactly one late-source fault")
    require(len(records) == log.count("PDCP_BATCH_INPUT "),
            "Malformed admission evidence")
    event, when, index = faults[0]
    key = tuple(lifecycle["source_key"])
    old_instance = lifecycle["old_instance"]
    new_instance = lifecycle["new_instance"]
    epoch = lifecycle["new_epoch"]

    require((int(event["ue"]), event["rb"]) == key, "Fault source key mismatch")
    require(int(event["old_instance"]) == old_instance
            and int(event["new_instance"]) == new_instance,
            "Fault generation mismatch")
    require(new_instance > old_instance > 0, "Invalid generation order")
    require(int(event["rx_pdus"]) > 0, "Replayed old report has no RX data")
    require(0 < index < len(records), "Missing replay admission")

    def same_key(item):
        return (int(item["ue"]), item["rb"]) == key

    candidate = records[index]
    if not (same_key(candidate) and
            int(candidate["instance"]) == old_instance):
        # The normal trigger report may still be queued when the producer
        # logs the replay event. Allow exactly that report before the replay.
        require(same_key(candidate)
                and int(candidate["instance"]) == new_instance
                and candidate["tx"] == candidate["rx"] == event["new_counter"]
                and candidate["accepted"] == "true"
                and int(candidate["status"]) == 0
                and int(candidate["epoch"]) == epoch
                and int(candidate["missing"]) == 0,
                "Unexpected admission before old-source replay")
        index += 1
        require(index < len(records), "Queued trigger lacks old-source replay")
    replay = records[index]
    require(same_key(replay) and int(replay["instance"]) == old_instance,
            "Next admission is not the replayed old source")
    require(replay["tx"] == replay["rx"] == event["old_counter"],
            "Replay counter mismatch")
    require(replay["rx_sdus"] == event["rx_sdus"]
            and replay["rx_pdus"] == event["rx_pdus"],
            "Replay payload mismatch")
    require(replay["accepted"] == "false" and int(replay["status"]) == 7,
            "Late old source was not rejected as stale_source")
    require(int(replay["revision"]) == 0 and int(replay["epoch"]) == epoch
            and int(replay["missing"]) == 0,
            "Stale rejection changed revision, epoch or missing count")

    originals = [
        item for item in records[:index]
        if same_key(item) and int(item["instance"]) == old_instance
        and item["accepted"] == "true"
        and item["rx"] == event["old_counter"]
    ]
    require(len(originals) == 1, "Replay has no unique real accepted original")
    original = originals[0]
    require(all(original[k] == replay[k] for k in (
        "tx", "rx", "rx_sdus", "rx_pdus")),
        "Replayed contents differ from the real original")

    previous = [
        item for item in records[:index]
        if same_key(item) and int(item["instance"]) == new_instance
        and item["accepted"] == "true"
    ]
    following = [
        item for item in records[index + 1:]
        if same_key(item) and item["accepted"] == "true"
    ]
    require(previous and following, "Missing new-source continuity evidence")
    before, after = previous[-1], following[0]
    require(int(before["rx"]) == int(event["new_counter"]),
            "Replay trigger counter mismatch")
    require(int(after["instance"]) == new_instance
            and int(after["status"]) == 0
            and int(after["epoch"]) == int(before["epoch"]) == epoch
            and int(after["rx"]) == int(before["rx"]) + 1
            and int(after["revision"]) == int(before["revision"]) + 1
            and int(after["missing"]) == 0,
            "New-source state did not continue normally after rejection")

    restarted = False
    for item in records:
        if not same_key(item):
            continue
        if int(item["instance"]) == new_instance and item["accepted"] == "true":
            restarted = True
        if restarted and item["accepted"] == "true":
            require(int(item["instance"]) == new_instance,
                    "An old source was accepted after reconstruction")

    ends = [
        datetime.fromisoformat(row["nominal_window_end_utc"].replace("Z", "+00:00"))
        for row in rows
    ]
    require(ends and min(ends) <= when <= max(ends),
            "Replay did not occur during post-reset KPM recording")
    after_queries = sum(when < t <= max(ends) + timedelta_seconds()
                        for t in query_times)
    require(after_queries >= 5, "Insufficient KPM calculations after replay")
    return {
        "passed": True, "fault_events": 1,
        "old_instance": old_instance, "new_instance": new_instance,
        "rejection_status": 7,
        "real_old_payload_matched": True,
        "new_source_continuity_checked": True,
        "post_fault_calculations": after_queries,
        "scope": "One real positive-RX old-source report replayed after reconstruction",
    }


def timedelta_seconds():
    from datetime import timedelta
    return timedelta(milliseconds=100)
