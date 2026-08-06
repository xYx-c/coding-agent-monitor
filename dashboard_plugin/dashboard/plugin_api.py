"""Authenticated dashboard proxy for the standalone coding-agent monitor.

The plugin never exposes the monitor bearer token to JavaScript. It only reads
an endpoint record for the profile selected when this dashboard process starts,
and it refuses anything except a 0600 token file and a loopback endpoint.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from hermes_constants import get_hermes_home
except ImportError:  # Plugin static tests may run outside a Hermes process.
    get_hermes_home = None

router = APIRouter()
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_MAX_RESPONSE = 1_048_576


class StartRun(BaseModel):
    agent: str
    workdir: str = Field(min_length=1, max_length=4096)
    task: str = Field(min_length=1, max_length=12_000)


def _profile_home() -> Path:
    """Resolve the dashboard's current profile home, rejecting ambiguous roots."""
    if get_hermes_home is None:
        raise HTTPException(503, "Hermes home unavailable")
    home = Path(get_hermes_home()).resolve()
    explicit = os.environ.get("HERMES_PROFILE")
    if explicit:
        # Explicit profile must agree with the profile-scoped Dashboard home.
        if home.parent.name != "profiles" or home.name != explicit:
            raise HTTPException(503, "dashboard profile/home mismatch")
        return home
    if home.parent.name == "profiles":
        return home
    raise HTTPException(503, "dashboard is not profile-scoped")


def active_profile() -> str:
    """Return the profile bound to the dashboard; never guess another profile."""
    return _profile_home().name


def _private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise HTTPException(503, "monitor credential is unavailable")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise HTTPException(503, "monitor credential permissions are unsafe")


def _endpoint() -> tuple[str, str]:
    """Load only this profile's loopback endpoint and private monitor token."""
    if get_hermes_home is None:
        raise HTTPException(503, "Hermes home unavailable")
    profile_home = _profile_home()
    profile = profile_home.name
    profile_dir = profile_home / "coding-agent-monitor" / "profiles" / profile
    endpoint_path = profile_dir / "endpoint.json"
    if endpoint_path.is_symlink() or not endpoint_path.is_file():
        raise HTTPException(503, "coding-agent monitor is not running")
    try:
        record = json.loads(endpoint_path.read_text(encoding="utf-8"))
        host, port = record["host"], int(record["port"])
        token_path = Path(record["token_path"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(503, "coding-agent monitor endpoint is invalid") from error
    if record.get("profile") != profile or host not in _LOOPBACK or not 1 <= port <= 65535:
        raise HTTPException(503, "coding-agent monitor endpoint is unsafe")
    # Token must remain inside the active profile monitor directory.
    try:
        token_path.resolve().relative_to(profile_dir.resolve())
    except ValueError as error:
        raise HTTPException(503, "coding-agent monitor token path is unsafe") from error
    _private_file(token_path)
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise HTTPException(503, "coding-agent monitor token is unavailable")
    return f"http://{host}:{port}", token


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Proxy to loopback monitor and translate failures without leaking credentials."""
    base, token = _endpoint()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        base + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(_MAX_RESPONSE + 1)
    except HTTPError as error:
        raw = error.read(_MAX_RESPONSE + 1)
        try:
            detail = json.loads(raw).get("error", "monitor request failed")
        except (json.JSONDecodeError, AttributeError):
            detail = "monitor request failed"
        raise HTTPException(error.code, str(detail)) from error
    except URLError as error:
        raise HTTPException(503, "coding-agent monitor is unavailable") from error
    if len(raw) > _MAX_RESPONSE:
        raise HTTPException(502, "monitor response is too large")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise HTTPException(502, "monitor returned invalid JSON") from error


def _run_path(run_id: str, suffix: str = "") -> str:
    # Service performs full run-id validation too; quote stops path injection.
    return f"/runs/{quote(run_id, safe='')}{suffix}"


@router.get("/runs")
def list_runs() -> Any:
    return _request("GET", "/runs")


@router.post("/runs")
def start_run(payload: StartRun) -> Any:
    return _request("POST", "/runs", {"agent": payload.agent, "workdir": payload.workdir, "task": payload.task, "profile": active_profile()})


@router.get("/runs/{run_id}")
def show_run(run_id: str) -> Any:
    return _request("GET", _run_path(run_id))


@router.get("/runs/{run_id}/output")
def run_output(run_id: str) -> Any:
    return _request("GET", _run_path(run_id, "/output"))


@router.post("/runs/{run_id}/refresh")
def refresh_run(run_id: str) -> Any:
    return _request("POST", _run_path(run_id, "/refresh"), {})


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str) -> Any:
    return _request("POST", _run_path(run_id, "/stop"), {"confirm": True})
