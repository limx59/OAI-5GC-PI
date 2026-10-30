#!/usr/bin/env python3
"""Isolated HTTP/2 routing fixture; never forwards authentication traffic."""

import json
import socket
import socketserver
import threading
import time

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, RequestReceived, ResponseReceived, StreamEnded


RECORDS = []
LOCK = threading.Lock()


def request(host, method, path, body=None, headers=None, timeout=10):
    """Perform one bounded h2c request without logging its body."""
    payload = json.dumps(body).encode() if body is not None else b""
    connection = H2Connection(config=H2Configuration(
        client_side=True, header_encoding="utf-8",
    ))
    with socket.create_connection((host, 7777), timeout=timeout) as sock:
        sock.settimeout(timeout)
        connection.initiate_connection()
        sock.sendall(connection.data_to_send())
        stream = connection.get_next_available_stream_id()
        fields = [
            (":method", method), (":scheme", "http"),
            (":authority", host + ":7777"), (":path", path),
            ("content-type", "application/json"),
        ]
        fields.extend((headers or {}).items())
        connection.send_headers(stream, fields, end_stream=not payload)
        if payload:
            connection.send_data(stream, payload, end_stream=True)
        sock.sendall(connection.data_to_send())

        status, content = None, bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(max(0.1, deadline - time.monotonic()))
            data = sock.recv(65535)
            if not data:
                raise RuntimeError("HTTP/2 connection closed before response")
            for event in connection.receive_data(data):
                if isinstance(event, ResponseReceived) and event.stream_id == stream:
                    status = int(dict(event.headers)[":status"])
                elif isinstance(event, DataReceived):
                    connection.acknowledge_received_data(
                        event.flow_controlled_length, event.stream_id,
                    )
                    if event.stream_id == stream:
                        content.extend(event.data)
                        if len(content) > 1048576:
                            raise RuntimeError("Fixture response limit exceeded")
                elif isinstance(event, StreamEnded) and event.stream_id == stream:
                    return status, json.loads(content) if content else None
            pending = connection.data_to_send()
            if pending:
                sock.sendall(pending)
    raise TimeoutError("HTTP/2 response timeout")


def respond(headers, peer):
    method = headers.get(":method", "")
    path = headers.get(":path", "")
    if method == "GET" and path == "/fixture/health":
        return 200, {"ready": True}
    if method == "GET" and path == "/fixture/records":
        with LOCK:
            return 200, {"records": list(RECORDS)}
    if method == "POST" and path.startswith("/nudm-ueau/"):
        with LOCK:
            RECORDS.append({
                "sequence": len(RECORDS) + 1,
                "peer_ip": peer,
                "service": "nudm-ueau",
                "target_apiroot": headers.get("3gpp-sbi-target-apiroot"),
                "discovery_service_names": headers.get(
                    "3gpp-sbi-discovery-service-names"
                ),
            })
        # Keep UE context alive to exercise subsequent authentication attempts.
        return 500, {
            "status": 500,
            "title": "Controlled routing fixture response",
            "cause": "SYSTEM_FAILURE",
        }
    return 404, {"status": 404, "title": "Unknown fixture endpoint"}


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        connection = H2Connection(config=H2Configuration(
            client_side=False, header_encoding="utf-8",
        ))
        streams = {}
        self.request.settimeout(60)
        try:
            connection.initiate_connection()
            self.request.sendall(connection.data_to_send())
            while True:
                data = self.request.recv(65535)
                if not data:
                    break
                for event in connection.receive_data(data):
                    if isinstance(event, RequestReceived):
                        streams[event.stream_id] = {
                            "headers": {
                                key.lower(): value for key, value in event.headers
                            },
                            "bytes": 0,
                        }
                    elif isinstance(event, DataReceived):
                        connection.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id,
                        )
                        streams[event.stream_id]["bytes"] += len(event.data)
                        if streams[event.stream_id]["bytes"] > 65536:
                            raise RuntimeError("Fixture request limit exceeded")
                    elif isinstance(event, StreamEnded):
                        state = streams.pop(event.stream_id)
                        status, body = respond(
                            state["headers"], self.client_address[0],
                        )
                        payload = json.dumps(body).encode()
                        connection.send_headers(event.stream_id, [
                            (":status", str(status)),
                            ("content-type", "application/problem+json"
                             if status >= 400 else "application/json"),
                            ("content-length", str(len(payload))),
                        ])
                        connection.send_data(
                            event.stream_id, payload, end_stream=True,
                        )
                pending = connection.data_to_send()
                if pending:
                    self.request.sendall(pending)
        except (ConnectionError, TimeoutError, OSError):
            pass
        except Exception as error:
            # Never print request bodies, paths or authentication data.
            print("Fixture connection error:", type(error).__name__, flush=True)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", 7777), Handler) as server:
        print("READY: isolated HTTP/2 routing fixture", flush=True)
        server.serve_forever()
