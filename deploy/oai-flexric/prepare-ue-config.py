#!/usr/bin/env python3
"""Create a local OAI UE configuration from an existing Open5GS subscriber."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent / "config/oai"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imsi", required=True)
    parser.add_argument("--mongo-container", default="mongo")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]{15}", args.imsi):
        parser.error("IMSI must contain exactly 15 digits.")

    path = DIRECTORY / "ue.conf"
    if path.exists():
        parser.error("ue.conf already exists; no changes made.")

    query = r'''
const s = db.subscribers.findOne({imsi:IMSI_VALUE});
if (!s) throw new Error("Subscriber not found");
const valid = v => typeof v === "string" && /^[0-9a-fA-F]{32}$/.test(v);
if (!s.security || !valid(s.security.k)) throw new Error("Invalid K");
let opc = s.security.opc;
if (!valid(opc)) {
  if (!valid(s.security.op)) throw new Error("Invalid OP");
  const crypto = require("crypto");
  const op = Buffer.from(s.security.op, "hex");
  const cipher = crypto.createCipheriv(
    "aes-128-ecb", Buffer.from(s.security.k, "hex"), null);
  cipher.setAutoPadding(false);
  const encrypted = Buffer.concat([cipher.update(op), cipher.final()]);
  opc = Buffer.from(encrypted.map((value, i) => value ^ op[i])).toString("hex");
}
print(JSON.stringify({imsi:s.imsi, k:s.security.k, opc:opc}));
'''.replace("IMSI_VALUE", json.dumps(args.imsi))

    result = subprocess.run(
        ["sudo", "docker", "exec", args.mongo_container, "mongosh",
         "--quiet", "open5gs", "--eval", query],
        capture_output=True, text=True,
    )
    if result.returncode:
        parser.error("Subscriber query or OPc conversion failed; no configuration written.")
    try:
        subscriber = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        parser.error("Invalid subscriber query response; no configuration written.")

    if subscriber.get("imsi") != args.imsi:
        parser.error("Unexpected IMSI; no configuration written.")
    for field in ("k", "opc"):
        value = subscriber.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", value):
            parser.error(f"Invalid {field}; no configuration written.")

    text = f'''# Local test credentials; do not commit.
uicc0 = {{
  imsi = "{subscriber["imsi"]}";
  key = "{subscriber["k"]}";
  opc = "{subscriber["opc"]}";
  pdu_sessions = ({{ dnn = "internet"; nssai_sst = 1; }});
}};

thread-pool = "-1,-1";

rfsimulator = (
  {{
    serveraddr = "172.29.0.30";
    serverport = 4043;
  }}
);
'''
    ignore = DIRECTORY / ".gitignore"
    ignored = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "ue.conf" not in ignored.splitlines():
        parser.error("Add ue.conf to config/oai/.gitignore before generating credentials.")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(text)
    print(f"Created local UE configuration for IMSI {args.imsi}, mode 0600.")
    print("DNN: internet; SST: 1; SD: absent. No database records changed.")


if __name__ == "__main__":
    main()
