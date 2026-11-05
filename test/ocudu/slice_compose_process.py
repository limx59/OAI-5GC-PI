#!/usr/bin/env python3
"""Adapt a Compose file-service Agent to the validator's process interface."""
import json
import os
from pathlib import Path
import subprocess
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class ComposeAgent:
    def __init__(self, compose, service, directory, stdout_path):
        self.compose = list(compose)
        self.service = service
        self.directory = Path(directory)
        self.stdout_path = Path(stdout_path)
        require(self.directory.is_dir(), "Missing Agent exchange directory")
        require(not self.stdout_path.exists(), "Agent transcript already exists")
        with self.stdout_path.open("x"):
            pass
        self.stdout_path.chmod(0o600)
        self.request_number = 0
        self.event_number = 0
        self.returncode = None
        self.stdin = self
        self._input = ""
        self._last_poll = 0
        self._command(self.compose + [
            "up", "-d", "--no-deps", "--no-build", "--pull", "never", service,
        ], timeout=60)
        self.cid = self._command(
            self.compose + ["ps", "--all", "-q", service]
        ).strip()
        require(self.cid and len(self.cid.splitlines()) == 1,
                "Missing or ambiguous Compose Agent")

    @staticmethod
    def _command(args, timeout=30):
        result = subprocess.run(
            ["sudo", "docker", *args],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        require(result.returncode == 0,
                "Compose Agent operation failed: "
                + (result.stdout + result.stderr)[-1500:])
        return result.stdout

    def _sync(self):
        while True:
            source = self.directory / f"event.{self.event_number + 1:06d}.json"
            if not source.is_file():
                break
            require(source.resolve().is_relative_to(self.directory.resolve())
                    and source.stat().st_size <= 8_388_608,
                    "Unexpected Agent event file")
            value = json.loads(source.read_text())
            require(isinstance(value, dict), "Invalid Agent event")
            with self.stdout_path.open("a") as stream:
                stream.write(json.dumps(value) + "\n")
            self.event_number += 1

    def write(self, value):
        require(isinstance(value, str), "Expected text request")
        self._input += value
        require(len(self._input) <= 8_388_608, "Oversized Agent request")

    def flush(self):
        while "\n" in self._input:
            line, self._input = self._input.split("\n", 1)
            value = json.loads(line)
            require(isinstance(value, dict), "Expected Agent request object")
            self.request_number += 1
            require(self.request_number <= 100, "Agent request limit exceeded")
            destination = self.directory / f"request.{self.request_number:06d}.json"
            temporary = self.directory / f".request.{self.request_number}.tmp"
            require(not destination.exists(), "Agent request already exists")
            with temporary.open("x") as stream:
                os.chmod(temporary, 0o600)
                json.dump(value, stream)
                stream.write("\n")
            os.replace(temporary, destination)

    def poll(self):
        self._sync()
        now = time.monotonic()
        if now - self._last_poll >= 0.2:
            item = json.loads(self._command(["inspect", self.cid]))[0]
            state = item["State"]
            self.returncode = None if state["Running"] else state["ExitCode"]
            self._last_poll = now
            self._sync()
        return self.returncode

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.service, timeout)
            time.sleep(0.1)
        return self.returncode

    def terminate(self):
        self._command(self.compose + ["stop", "--timeout", "5", self.service])

    def kill(self):
        self._command(self.compose + ["kill", self.service])

    def close(self):
        require(not self._input, "Incomplete Agent request")
        (self.directory / "finish").touch()
