"""Token-authenticated loopback HTTP API for one Hermes profile."""

from __future__ import annotations

import json
import os
import secrets
import stat
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .redaction import redact_value
from .service import MonitorError, Supervisor
from .state import PROFILE_RE, atomic_json, ensure_private_dir

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_MAX_BODY = 16_384


def profile_token(supervisor: Supervisor, profile: str) -> tuple[str, Path]:
    """Load or create the active profile's owner-only API token."""
    if not PROFILE_RE.fullmatch(profile):
        raise MonitorError("invalid profile")
    directory = ensure_private_dir(supervisor.profiles / profile)
    path = directory / "api.token"
    if path.exists():
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise MonitorError("unsafe API token file")
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise MonitorError("API token file is empty")
        return token, path
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return token, path


def serve(supervisor: Supervisor, profile: str = "default", host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Create the loopback-only monitor HTTP server and endpoint record."""
    if host not in _LOOPBACK:
        raise MonitorError("refusing non-loopback bind address")
    token, token_path = profile_token(supervisor, profile)

    class Handler(BaseHTTPRequestHandler):
        server_version = "coding-agent-monitor/0.2"

        def log_message(self, format: str, *_args: Any) -> None:
            del format
            return

        def _authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}")

        def _json(self, status: int, payload: Any) -> None:
            encoded = json.dumps(redact_value(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if length < 0 or length > _MAX_BODY:
                raise ValueError("request body too large")
            try:
                value = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as error:
                raise ValueError("invalid JSON") from error
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value

        def _run_id(self, path: str, suffix: str = "") -> str | None:
            if not path.startswith("/runs/") or (suffix and not path.endswith(suffix)):
                return None
            value = path[6:len(path) - len(suffix) if suffix else None].rstrip("/")
            return value or None

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            path = urlsplit(self.path).path
            try:
                if path == "/health":
                    self._json(HTTPStatus.OK, {"ok": True, "profile": profile})
                elif path == "/runs":
                    self._json(HTTPStatus.OK, {"runs": supervisor.list(profile)})
                elif (run_id := self._run_id(path, "/output")) is not None:
                    self._json(HTTPStatus.OK, {"run_id": run_id, "output": supervisor.output(run_id, profile)})
                elif (run_id := self._run_id(path)) is not None:
                    self._json(HTTPStatus.OK, supervisor.show(run_id, profile))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except MonitorError as error:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(error)})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            path = urlsplit(self.path).path
            try:
                body = self._body()
                if path == "/runs":
                    if body.get("profile") != profile or not all(isinstance(body.get(key), str) and body[key].strip() for key in ("agent", "workdir", "task")):
                        raise ValueError("agent, workdir, task, and matching profile are required")
                    self._json(HTTPStatus.CREATED, supervisor.start(body["agent"], body["workdir"], body["task"], profile))
                elif (run_id := self._run_id(path, "/refresh")) is not None:
                    self._json(HTTPStatus.OK, supervisor.refresh(run_id, profile))
                elif (run_id := self._run_id(path, "/stop")) is not None:
                    if body.get("confirm") is not True:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": "confirm must be true"})
                    else:
                        self._json(HTTPStatus.OK, supervisor.stop(run_id, profile))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ValueError, MonitorError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    httpd = ThreadingHTTPServer((host, port), Handler)
    address, selected_port = httpd.server_address[:2]
    endpoint = ensure_private_dir(supervisor.profiles / profile) / "endpoint.json"
    atomic_json(endpoint, {"host": address, "port": selected_port, "token_path": str(token_path), "profile": profile})
    return httpd
