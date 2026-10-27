"""Controlled RRC release and PDCP source-reconstruction diagnostics."""

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import subprocess
import tempfile
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def paired_inputs(log):
    """Associate each source-ID record with its following admission record."""
    result = []
    pending = None
    for line in log.splitlines():
        if "PDCP_SOURCE_ID " in line:
            require(pending is None, "Source-ID record lacks admission")
            fields = dict(re.findall(r"(\w+)=([^\s]+)", line))
            pending = {
                "ue": int(fields["ue"]), "rb": fields["rb"],
                "instance": int(fields["instance"]),
                "tx": int(fields["tx"]), "rx": int(fields["rx"]),
            }
        elif "PDCP_BATCH_INPUT " in line:
            require(pending is not None, "Admission lacks source identity")
            fields = dict(re.findall(r"(\w+)=([^\s]+)", line))
            require(
                (pending["ue"], pending["rb"], pending["tx"], pending["rx"])
                == (int(fields["ue"]), fields["rb"],
                    int(fields["tx"]), int(fields["rx"])),
                "Source-ID/admission mismatch",
            )
            result.append({
                **pending,
                "status": int(fields["status"]),
                "accepted": fields["accepted"] == "true",
                "revision": int(fields["revision"]),
                "epoch": int(fields["epoch"]),
                "missing": int(fields["missing"]),
            })
            pending = None
    # A live log snapshot may end between identity and admission.
    return result


def discover_target(config_text, log):
    pcis = {
        int(value) for value in re.findall(
            r"(?m)^\s*pci:\s*(\d+)\s*(?:#.*)?$", config_text)
    }
    active = {}
    pattern = re.compile(
        r"(?<![\w-])(?:c-rnti|crnti|rnti)\s*[=:]\s*(0x[0-9a-f]+)\b",
        re.I,
    )
    for line in log.splitlines():
        creating = 'proc="MAC UE Creation": finished successfully' in line
        removing = 'proc="MAC UE Removal": finished successfully' in line
        if not (creating or removing):
            continue
        rntis = {int(value, 16) for value in pattern.findall(line)}
        ues = re.findall(r"(?<![\w-])ue=(\d+)\b", line)
        require(len(rntis) == 1 and len(set(ues)) == 1,
                "Malformed MAC UE lifecycle identity")
        rnti, ue = next(iter(rntis)), int(ues[0])
        if creating:
            require(rnti not in active, "Duplicate active RNTI creation")
            active[rnti] = ue
        else:
            require(active.get(rnti) == ue,
                    "UE removal lacks matching creation")
            del active[rnti]

    require(len(pcis) == 1, "Expected one configured PCI")
    require(len(active) == 1, "Cannot identify one unambiguous active RNTI")
    pci, rnti = next(iter(pcis)), next(iter(active))
    require(0 <= pci <= 1007 and 0 < rnti < 65535, "Invalid release target")
    return pci, rnti



def run_probe(dest, command, inspect, identity, gnb, ue, test_ric):
    dest = Path(dest)
    result = {
        "passed": False,
        "scope": "Live RRC release and same-key PDCP source reconstruction",
        "post_reset_kpm_calculation_validated": False,
        "late_old_source_injection_validated": False,
    }
    before = {name: identity(name) for name in (gnb, ue, test_ric)}
    require(all(value["running"] for value in before.values()),
            "Lifecycle probe requires running test components")
    require(inspect(gnb)["Config"]["OpenStdin"],
            "Test gNB requires stdin_open: true")
    initial_log = command(["logs", "--timestamps", gnb], timeout=30)
    initial = paired_inputs(initial_log)
    require(len(initial) >= 5, "Insufficient initial source evidence")
    keys = {(item["ue"], item["rb"]) for item in initial}
    require(len(keys) == 1, "Expected one initial PDCP source key")
    source_key = next(iter(keys))
    generations = {item["instance"] for item in initial}
    require(len(generations) == 1, "Initial source was already replaced")
    old_instance = next(iter(generations))
    old = initial[-1]
    require(old["accepted"] and old["instance"] > 0,
            "Initial source admission invalid")
    pci, rnti = discover_target((dest / "gnb.yml").read_text(), initial_log)
    release_command = f"release {pci} {rnti:x}\n"
    result.update({
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "before": before,
        "target": {"pci": pci, "rnti_hex": f"{rnti:x}"},
        "source_key": list(source_key),
        "old_instance": old_instance,
        "old_counter": old["rx"],
        "old_epoch": old["epoch"],
    })
    (dest / "rrc-release-command.txt").write_text(release_command)

    client = None
    ping_client = None
    try:
        with tempfile.TemporaryFile(mode="w+t") as attach_output, \
             (dest / "lifecycle-ping.log").open("x") as ping_output:
            # Signals to this Docker client must never propagate to the gNB.
            client = subprocess.Popen(
                ["sudo", "docker", "attach", "--sig-proxy=false", gnb],
                stdin=subprocess.PIPE, stdout=attach_output,
                stderr=subprocess.STDOUT, text=True,
            )
            client.stdin.write(release_command)
            client.stdin.flush()

            deadline = time.monotonic() + 90
            triggered = False
            new_records = []
            while time.monotonic() < deadline:
                for name, previous in before.items():
                    require(identity(name) == previous,
                            f"Component identity changed: {name}")
                log = command(["logs", "--timestamps", gnb], timeout=15)
                tail = log[len(initial_log):] if log.startswith(initial_log) else ""
                if "RRC Release triggered for UE pci=" in tail:
                    triggered = True
                    if ping_client is None:
                        ping_client = subprocess.Popen(
                            ["sudo", "docker", "exec", ue,
                             "ping", "-I", "oaitun_ue1",
                             "-i", "1", "-c", "60", "-W", "1", "172.22.0.151"],
                            stdin=subprocess.DEVNULL,
                            stdout=ping_output, stderr=subprocess.STDOUT,
                        )
                records = paired_inputs(log)
                new_records = [
                    item for item in records
                    if (item["ue"], item["rb"]) == source_key
                    and item["instance"] > old_instance
                ]
                if triggered and len(new_records) >= 3:
                    break
                time.sleep(1)

            require(triggered, "RRC release command acknowledgement not observed")
            require(len(new_records) >= 3, "Same-key PDCP reconstruction timeout")
            first = new_records[0]
            require(first["accepted"] and first["status"] == 6,
                    "New source did not trigger source_restart admission")
            require(first["epoch"] == old["epoch"] + 1,
                    "Source epoch did not advance exactly once")
            require(first["rx"] < old["rx"], "Counter restart not demonstrated")
            require(first["missing"] == 0, "Restart was incorrectly counted as a gap")
            require(first["revision"] > old["revision"],
                    "Revision did not advance across reconstruction")
            require(len({item["instance"] for item in new_records}) == 1,
                    "More than one replacement source appeared")
            for previous, current in zip(new_records, new_records[1:]):
                require(current["accepted"] and current["status"] == 0,
                        "Post-restart batch was not accepted normally")
                require(current["rx"] == previous["rx"] + 1,
                        "Post-restart counters are not consecutive")
                require(current["epoch"] == first["epoch"],
                        "Post-restart epoch changed")

            output = command(
                ["exec", ue, "ping", "-I", "oaitun_ue1",
                 "-c", "3", "-W", "2", "172.22.0.151"], timeout=20)
            (dest / "post-reconstruction-ping.log").write_text(output)
            for name, previous in before.items():
                require(identity(name) == previous,
                        f"Component changed after reconstruction: {name}")
            result.update({
                "passed": True,
                "new_instance": first["instance"],
                "new_counter": first["rx"],
                "new_epoch": first["epoch"],
                "post_restart_batches": len(new_records),
                "post_restart_ping_passed": True,
                "component_identities_unchanged": True,
            })
    finally:
        for process in (ping_client, client):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (dest / "lifecycle-probe.json").write_text(
            json.dumps(result, indent=2) + "\n")
    return result
