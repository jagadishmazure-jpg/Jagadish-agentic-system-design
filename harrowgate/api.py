"""Tiny HTTP front door (stdlib only) used by the container image.

POST /v1/assist {"passenger_id": "P-1001", "text": "..."} -> status, messages, destination, trace id.
GET  /healthz -> ok. Input is size-limited and validated; responses never echo names or emails.
In Azure the app sits behind Container Apps ingress with Entra ID authentication (docs/deployment.md).
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .system import Config, System
from .world import default_world

_PID = re.compile(r"^P-\d{4}$")
MAX_TEXT = 500


def assist(body: dict, system: System) -> tuple[int, dict]:
    if not isinstance(body, dict) or set(body) - {"passenger_id", "text"}:
        return 400, {"error": "body must be an object with passenger_id and text only"}
    pid, text = body.get("passenger_id"), body.get("text")
    if not isinstance(pid, str) or not _PID.match(pid) or pid not in system.world.passengers:
        return 404, {"error": "unknown passenger"}
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        return 400, {"error": f"text must be 1-{MAX_TEXT} characters"}
    resp = system.handle({"passenger_id": pid, "text": text})
    return 200, {"status": resp.status, "messages": resp.messages, "destination": resp.destination,
                 "route": resp.route, "trace_id": resp.run_id}


def make_handler(system: System):
    lock = threading.Lock()  # one simulated world per process: serialise requests

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            self._send(200, {"ok": True}) if self.path == "/healthz" else self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/v1/assist":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > 4096:
                return self._send(413, {"error": "body too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid JSON"})
            with lock:
                code, payload = assist(body, system)
            self._send(code, payload)

        def log_message(self, *args):  # keep request text out of logs
            pass

    return Handler


def serve(port: int = 8080) -> None:  # pragma: no cover - network loop
    system = System(default_world(), Config())
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(system)).serve_forever()  # noqa: S104 - container port
