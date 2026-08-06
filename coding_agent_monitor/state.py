"""Small, defensive file and state helpers for monitor-owned data."""

from __future__ import annotations

import json
import os
import re
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

PROFILE_RE = re.compile(r"[A-Za-z0-9_.-]+")
RUN_ID_RE = re.compile(r"[0-9a-f]{24}")


class TransitionError(ValueError):
    """A run attempted an invalid state transition."""


class RunState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    DISCONNECTED = "disconnected"


_ALLOWED: dict[RunState, set[RunState]] = {
    RunState.STARTING: {RunState.STARTING, RunState.RUNNING, RunState.WAITING_INPUT, RunState.WAITING_APPROVAL, RunState.TESTING, RunState.COMPLETED, RunState.FAILED, RunState.STOPPED, RunState.DISCONNECTED},
    RunState.RUNNING: {RunState.RUNNING, RunState.WAITING_INPUT, RunState.WAITING_APPROVAL, RunState.TESTING, RunState.COMPLETED, RunState.FAILED, RunState.STOPPED, RunState.DISCONNECTED},
    RunState.WAITING_INPUT: {RunState.WAITING_INPUT, RunState.RUNNING, RunState.TESTING, RunState.COMPLETED, RunState.FAILED, RunState.STOPPED, RunState.DISCONNECTED},
    RunState.WAITING_APPROVAL: {RunState.WAITING_APPROVAL, RunState.RUNNING, RunState.TESTING, RunState.COMPLETED, RunState.FAILED, RunState.STOPPED, RunState.DISCONNECTED},
    RunState.TESTING: {RunState.TESTING, RunState.RUNNING, RunState.COMPLETED, RunState.FAILED, RunState.STOPPED, RunState.DISCONNECTED},
    RunState.COMPLETED: {RunState.COMPLETED},
    RunState.FAILED: {RunState.FAILED},
    RunState.STOPPED: {RunState.STOPPED},
    RunState.DISCONNECTED: {RunState.DISCONNECTED, RunState.STOPPED},
}


def validate_transition(old: RunState | str, new: RunState | str) -> RunState:
    """Validate and normalize a monitor state transition."""
    try:
        before, after = RunState(old), RunState(new)
    except ValueError as error:
        raise TransitionError("unknown run state") from error
    if after not in _ALLOWED[before]:
        raise TransitionError(f"invalid transition: {before.value} -> {after.value}")
    return after


def ensure_private_dir(path: Path) -> Path:
    """Create an owner-only directory while rejecting symlink paths."""
    if path.exists() and path.is_symlink():
        raise ValueError("unsafe symlink path")
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("expected directory")
    os.chmod(path, 0o700)
    return path


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically write private JSON, so readers never observe partial files."""
    ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_json(path: Path) -> dict[str, Any]:
    """Read a plain JSON object and refuse symlinks or non-files."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or unsafe JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value
