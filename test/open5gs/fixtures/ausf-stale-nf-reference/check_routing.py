#!/usr/bin/env python3
"""Compare real AUSF binaries using controlled HTTP/2 lifecycle messages."""

import json
from pathlib import Path
import socket
import time

from sbi_fixture import request


UDM_ID = "00000000-0000-4000-8000-000000000013"
UDM_ROOT = "http://192.0.2.13:7777"
NOTIFY = "/nnrf-nfm/v1/nf-status-notify"
AUTH = "/nausf-auth/v1/ue-authentications"
OUTPUT = Path("/evidence/routing-summary.json")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def wait_ready(host, fixture=False):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            status, _ = request(
                host, "GET", "/fixture/health" if fixture else AUTH,
                timeout=2,
            )
            if (fixture and status == 200) or (
                not fixture and status in (400, 403, 404, 405)
            ):
                return
        except (OSError, RuntimeError, TimeoutError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Readiness timeout: " + host)


def notify(host, registered):
    body = {
        "event": "NF_REGISTERED" if registered else "NF_DEREGISTERED",
        "nfInstanceUri": (
            "http://fixture:7777/nnrf-nfm/v1/nf-instances/" + UDM_ID
        ),
    }
    if registered:
        body["nfProfile"] = {
            "nfInstanceId": UDM_ID,
            "nfType": "UDM",
            "nfStatus": "REGISTERED",
            "ipv4Addresses": ["192.0.2.13"],
            "allowedNfTypes": ["AUSF", "SCP"],
            "nfServices": [{
                "serviceInstanceId": "00000000-0000-4000-8000-000000000014",
                "serviceName": "nudm-ueau",
                "versions": [{
                    "apiVersionInUri": "v1", "apiFullVersion": "1.0.0",
                }],
                "scheme": "http",
                "nfServiceStatus": "REGISTERED",
                "ipEndPoints": [{"ipv4Address": "192.0.2.13", "port": 7777}],
                "allowedNfTypes": ["AUSF", "SCP"],
            }],
        }
    status, _ = request(
        host, "POST", NOTIFY, body, {"user-agent": "NRF"},
    )
    require(status == 204, f"{host}: lifecycle notification returned {status}")


def records(host):
    status, body = request("fixture", "GET", "/fixture/records")
    require(status == 200, "Cannot read fixture records")
    address = socket.gethostbyname(host)
    return [item for item in body["records"] if item["peer_ip"] == address]


def authenticate(host):
    before = len(records(host))
    status, _ = request(host, "POST", AUTH, {
        # Synthetic identity only; no real subscriber or authentication keys.
        "supiOrSuci": "suci-0-001-01-0000-0-0-0000000001",
        "servingNetworkName": "5G:mnc001.mcc001.3gppnetwork.org",
    }, {"user-agent": "AMF"})
    require(status == 500, f"{host}: expected controlled HTTP 500, got {status}")
    after = records(host)
    require(len(after) == before + 1, f"{host}: unexpected routing record count")
    return after[-1]


def check_control():
    host = "ausf-control"
    wait_ready(host)
    notify(host, True)
    first = authenticate(host)
    require(first["target_apiroot"] == UDM_ROOT,
            "Control did not initially use advertised service port")
    notify(host, False)
    retry = authenticate(host)
    require(retry["target_apiroot"] in (
        "http://192.0.2.13", "http://192.0.2.13:80",
    ), "Original-image defect was not reproduced")
    return {
        "defect_reproduced": True,
        "before_deregistration": first,
        "after_deregistration": retry,
    }


def check_patched():
    host = "ausf-patched"
    wait_ready(host)
    notify(host, True)
    first = authenticate(host)
    require(first["target_apiroot"] == UDM_ROOT,
            "Patched AUSF did not initially use advertised service port")
    cycles = []
    for number in range(1, 4):
        notify(host, False)
        retry = authenticate(host)
        require(retry["target_apiroot"] is None,
                "Patched AUSF retained a target after UDM removal")
        require("nudm-ueau" in (retry["discovery_service_names"] or ""),
                "Patched AUSF did not request fresh service discovery")

        notify(host, True)
        restored = authenticate(host)
        require(restored["target_apiroot"] == UDM_ROOT,
                "Patched AUSF did not restore the advertised service port")
        cycles.append({
            "cycle": number,
            "after_deregistration": retry,
            "after_registration": restored,
        })
    return {"initial": first, "cycles": cycles}


def main():
    result = {
        "passed": False,
        "scope": "Real AUSF routing and cache invalidation with synthetic SBI peers",
        "real_ue_authentication_validated": False,
        "real_nrf_heartbeat_recovery_validated": False,
        "fixture_authentication_response": 500,
    }
    try:
        wait_ready("fixture", fixture=True)
        result["control"] = check_control()
        result["patched"] = check_patched()
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
