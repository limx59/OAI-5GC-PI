#!/usr/bin/env python3
"""Bridge a lab JSON-line worker to private Compose exchange files.

The caller atomically publishes request.000001.json, then subsequent
numbered requests. Worker JSON records become event.000001.json, etc.
A finish file closes worker stdin. No network listener is opened.
"""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    directory = args.directory.resolve()
    require(directory.is_relative_to(Path("/exchange"))
            and directory.is_dir(), "Expected mounted exchange directory")
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    require(command, "Missing worker command")
    require(not list(directory.glob("event.*.json")),
            "Exchange contains old worker events")
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        bufsize=0,
    )
    request_number = event_number = 0
    stdin_closed = False
    pending_output = b""
    deadline = time.monotonic() + 300
    try:
        while True:
            require(time.monotonic() < deadline,
                    "File service exceeded laboratory time bound")
            if not stdin_closed:
                path = directory / f"request.{request_number + 1:06d}.json"
                if path.is_file():
                    require(request_number < 100, "Request limit exceeded")
                    require(path.resolve().is_relative_to(directory),
                            "Request outside exchange directory")
                    require(path.stat().st_size <= 8_388_608,
                            "Oversized worker request")
                    value = json.loads(path.read_text())
                    require(isinstance(value, dict), "Expected request object")
                    process.stdin.write((json.dumps(value) + "\n").encode())
                    process.stdin.flush()
                    request_number += 1
                elif (directory / "finish").is_file():
                    process.stdin.close()
                    stdin_closed = True

            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    require(not pending_output, "Incomplete final worker event")
                    break
                pending_output += chunk
            while b"\n" in pending_output:
                line, pending_output = pending_output.split(b"\n", 1)
                require(len(line) <= 8_388_608, "Oversized worker event")
                value = json.loads(line)
                require(isinstance(value, dict), "Expected worker event object")
                event_number += 1
                require(event_number <= 100, "Event limit exceeded")
                destination = directory / f"event.{event_number:06d}.json"
                temporary = directory / f".event.{event_number:06d}.tmp"
                require(not destination.exists(), "Worker event already exists")
                with temporary.open("x") as stream:
                    os.chmod(temporary, 0o600)
                    json.dump(value, stream)
                    stream.write("\n")
                os.replace(temporary, destination)

            require(len(pending_output) <= 8_388_608,
                    "Oversized incomplete worker event")

        process.wait(timeout=5)
        require(process.returncode == 0, "Worker exited unsuccessfully")
        print(json.dumps({
            "passed": True,
            "requests_forwarded": request_number,
            "events_saved": event_number,
        }), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
