#!/usr/bin/env python3
"""Exchange requests with the actual Compose coordinator container."""
import json
from pathlib import Path
import runpy
import time

Channel = runpy.run_path(str(
    Path(__file__).with_name("slice_compose_process.py")
))["ComposeAgent"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class ComposeCoordinator:
    def __init__(self, compose, directory, transcript, retain):
        self.channel = Channel(
            compose, "coordinator", directory, transcript
        )
        self.retain = retain
        self.request_id = 0
        self.initialized = False
        self.last_response = None

    def request(self, operation, **fields):
        self.request_id += 1
        require(self.request_id <= 100, "Coordinator request limit exceeded")
        request = {
            "request_id": self.request_id,
            "operation": operation,
            **fields,
        }
        sent = time.monotonic()
        self.retain(f"coordinator.request.{self.request_id}.json", {
            "host_sent_s": sent, "payload": request,
        })
        self.channel.write(json.dumps(request) + "\n")
        self.channel.flush()
        deadline = time.monotonic() + 20
        response = None
        while time.monotonic() < deadline:
            status = self.channel.poll()
            records = [
                json.loads(line)
                for line in self.channel.stdout_path.read_text().splitlines()
                if line.strip()
            ]
            matches = [
                item for item in records
                if item.get("request_id") == self.request_id
            ]
            require(len(matches) <= 1, "Duplicate coordinator response")
            if matches:
                response = matches[0]
                break
            require(status is None,
                    "Coordinator exited before responding")
            time.sleep(0.05)
        require(response is not None, "Coordinator response timed out")
        received = time.monotonic()
        self.retain(f"coordinator.response.{self.request_id}.json", {
            "host_received_s": received, "payload": response,
        })
        require(response.get("passed") is True,
                "Coordinator rejected request: " + str(response.get("error")))
        require(response.get("control_requests_sent") == 0,
                "Unexpected coordinator transport behavior")
        self.last_response = response
        return response

    def initialize(self, sources, initial_max_ratio=100):
        require(not self.initialized, "Coordinator already initialized")
        response = self.request(
            "initialize", sources=sources,
            initial_max_ratio=initial_max_ratio,
        )
        require(response["result"]["status"] == "initialized"
                and response["committed_max_ratio"] == 100
                and response["pending_plan"] is None,
                "Unexpected initialized coordinator state")
        self.initialized = True
        return response

    def evaluate(self, revision, reports):
        require(self.initialized, "Coordinator not initialized")
        return self.request("evaluate", revision=revision, reports=reports)

    def complete(self, generation, node_outcomes):
        require(self.initialized, "Coordinator not initialized")
        return self.request(
            "complete", generation=generation, node_outcomes=node_outcomes
        )

    def finish(self):
        self.channel.close()
        require(self.channel.wait(timeout=10) == 0,
                "Coordinator did not finish successfully")
