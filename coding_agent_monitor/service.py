"""Profile-scoped local supervisor for isolated Claude Code and Codex runs."""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .command import ValidationError, build_command, validate_workdir
from .redaction import redact_text, redact_value, safe_task_summary
from .state import PROFILE_RE, RUN_ID_RE, RunState, atomic_json, ensure_private_dir, read_json, validate_transition
from .tmux import TmuxClient, TmuxError


class MonitorError(RuntimeError):
    """A safe error message suitable for CLI or local API callers."""


_TEST_RE = re.compile(r"\b(cargo|pytest|npm|pnpm|test|build|check)\b", re.IGNORECASE)
_EXIT_RE = re.compile(r"\[monitor agent exit=(\d+)\]")
_TERMINAL = {RunState.COMPLETED, RunState.FAILED, RunState.STOPPED}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Supervisor:
    """Operate only generated monitor run directories and private tmux sessions."""

    def __init__(self, home: str | Path | None = None, tmux: Any | None = None) -> None:
        hermes_home = Path(home or os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
        self.root = ensure_private_dir(hermes_home / "coding-agent-monitor")
        self.runs = ensure_private_dir(self.root / "runs")
        self.profiles = ensure_private_dir(self.root / "profiles")
        self.tmux = tmux or TmuxClient()
        self._scrub_existing_records()

    def _scrub_existing_records(self) -> None:
        """Re-sanitize legacy monitor-owned files before any endpoint can return them."""
        for directory in self.runs.iterdir():
            if not directory.is_dir() or not RUN_ID_RE.fullmatch(directory.name):
                continue
            for name in ("terminal.ansi", "events.jsonl"):
                path = directory / name
                if path.is_symlink() or not path.is_file():
                    continue
                original = path.read_text(encoding="utf-8", errors="replace")
                sanitized = redact_text(original)
                if sanitized != original:
                    path.write_text(sanitized, encoding="utf-8")
                    os.chmod(path, 0o600)

    def _paths(self, run_id: str) -> dict[str, Path]:
        if not RUN_ID_RE.fullmatch(run_id):
            raise MonitorError("invalid run id")
        run = self.runs / run_id
        return {
            "run": run,
            "manifest": run / "manifest.json",
            "status": run / "status.json",
            "events": run / "events.jsonl",
            "terminal": run / "terminal.ansi",
            "script": run / "launch.sh",
            "owner": run / "ownership.token",
        }

    def _manifest(self, run_id: str, profile: str | None = None) -> dict[str, Any]:
        try:
            manifest = read_json(self._paths(run_id)["manifest"])
        except ValueError as error:
            raise MonitorError(str(error)) from error
        if manifest.get("run_id") != run_id or manifest.get("session") != f"cam-{run_id}":
            raise MonitorError("manifest does not own this session")
        if profile is not None and manifest.get("profile") != profile:
            raise MonitorError("run is not owned by this profile")
        return manifest

    def _status(self, run_id: str) -> dict[str, Any]:
        try:
            status = read_json(self._paths(run_id)["status"])
            RunState(status["state"])
            return status
        except (KeyError, ValueError) as error:
            raise MonitorError(f"invalid status for run {run_id}") from error

    def _owner(self, run_id: str) -> str:
        path = self._paths(run_id)["owner"]
        if path.is_symlink() or not path.is_file():
            raise MonitorError("missing ownership token")
        return path.read_text(encoding="utf-8").strip()

    def _write_status(self, run_id: str, old: RunState, new: RunState, **extra: Any) -> dict[str, Any]:
        validate_transition(old, new)
        status = {"run_id": run_id, "state": new.value, "updated_at": _now(), **redact_value(extra)}
        atomic_json(self._paths(run_id)["status"], status)
        return status

    def _transition_or_keep(self, run_id: str, old: RunState, target: RunState, **extra: Any) -> dict[str, Any]:
        if old in _TERMINAL and target != old:
            target = old
        return self._write_status(run_id, old, target, **extra)

    def _recent_events(self, run_id: str, limit: int = 20) -> list[dict[str, Any]]:
        path = self._paths(run_id)["events"]
        if not path.exists():
            return []
        if path.is_symlink() or not path.is_file():
            raise MonitorError("unsafe events file")
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(redact_value(event))
        return events

    def _public(self, manifest: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        return redact_value({"manifest": manifest, "status": status, "recent_events": self._recent_events(manifest["run_id"])})

    def _task_file(self, task: str) -> Path:
        """Create owner-only ephemeral input outside monitor run records."""
        directory = "/dev/shm" if Path("/dev/shm").is_dir() else None
        fd, raw = tempfile.mkstemp(prefix="cam-task-", dir=directory, text=True)
        path = Path(raw)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(task)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def start(self, agent: str, workdir: str | Path, task: str, profile: str = "default") -> dict[str, Any]:
        """Validate a run then launch it only via the dedicated private socket."""
        if not PROFILE_RE.fullmatch(profile):
            raise MonitorError("invalid profile")
        if not task.strip():
            raise MonitorError("task must not be empty")
        try:
            worktree, branch, head = validate_workdir(workdir)
            command = build_command(agent, worktree)
        except ValidationError as error:
            raise MonitorError(str(error)) from error
        run_id = secrets.token_hex(12)
        paths = self._paths(run_id)
        ensure_private_dir(paths["run"])
        owner = secrets.token_urlsafe(32)
        paths["owner"].write_text(owner + "\n", encoding="utf-8")
        os.chmod(paths["owner"], 0o600)
        task_path = self._task_file(task)
        script = (
            "#!/bin/sh\nset -eu\n"
            f"TASK_FILE={shlex.quote(str(task_path))}\n"
            "cleanup() { rm -f -- \"$TASK_FILE\"; }\ntrap cleanup EXIT HUP INT TERM\n"
            f"cd {shlex.quote(str(worktree))}\n{shlex.join(command)} < \"$TASK_FILE\"\n"
        )
        paths["script"].write_text(script, encoding="utf-8")
        os.chmod(paths["script"], 0o700)
        manifest = {
            "version": 1, "run_id": run_id, "profile": profile, "agent": agent,
            "session": f"cam-{run_id}", "workdir": str(worktree), "git_branch": branch,
            "git_head": head, "task_summary": safe_task_summary(task), "created_at": _now(),
        }
        atomic_json(paths["manifest"], manifest)
        self._write_status(run_id, RunState.STARTING, RunState.STARTING, phase="launching")
        try:
            self.tmux.create(manifest["session"], paths["script"], owner)
        except TmuxError as error:
            task_path.unlink(missing_ok=True)
            status = self._write_status(run_id, RunState.STARTING, RunState.DISCONNECTED, error=str(error))
            return self._public(manifest, status)
        return self.refresh(run_id, profile)

    def _derive_events(self, text: str) -> tuple[RunState | None, list[dict[str, Any]]]:
        state: RunState | None = None
        events: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            if _TEST_RE.search(raw_line):
                state = RunState.TESTING
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            labels = " ".join(str(event.get(key, "")) for key in ("type", "event", "subtype", "status")).lower()
            if any(token in labels for token in ("approval", "permission")):
                state = RunState.WAITING_APPROVAL
            elif "input" in labels or "question" in labels:
                state = RunState.WAITING_INPUT
            elif "error" in labels or "failed" in labels:
                state = RunState.FAILED
            elif "complete" in labels or "finished" in labels:
                state = RunState.COMPLETED
            elif labels:
                state = state or RunState.RUNNING
            events.append({"at": _now(), "event": redact_value(event), "derived_state": state.value if state else None})
        return state, events

    def _append_events(self, path: Path, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        with path.open("a", encoding="utf-8") as handle:
            os.chmod(path, 0o600)
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")

    def refresh(self, run_id: str, profile: str | None = None) -> dict[str, Any]:
        """Capture and redact private-pane output, then update derived state."""
        manifest, old, paths = self._manifest(run_id, profile), self._status(run_id), self._paths(run_id)
        old_state, session, owner = RunState(old["state"]), manifest["session"], self._owner(run_id)
        try:
            if not self.tmux.exists(session):
                target = RunState.STOPPED if old_state == RunState.STOPPED else RunState.DISCONNECTED
                return self._public(manifest, self._transition_or_keep(run_id, old_state, target, phase="session_missing"))
            if not self.tmux.owned(session, owner):
                return self._public(manifest, self._transition_or_keep(run_id, old_state, RunState.DISCONNECTED, error="session ownership mismatch"))
            captured = redact_text(self.tmux.capture(session))
            previous = paths["terminal"].read_text(encoding="utf-8") if paths["terminal"].exists() else ""
            paths["terminal"].write_text(captured, encoding="utf-8")
            os.chmod(paths["terminal"], 0o600)
            event_state, events = self._derive_events(captured[len(previous):] if captured.startswith(previous) else captured)
            self._append_events(paths["events"], events)
            exit_match = _EXIT_RE.search(captured)
            if exit_match:
                target = RunState.COMPLETED if exit_match.group(1) == "0" else RunState.FAILED
            else:
                target = event_state or (old_state if old_state in {RunState.WAITING_INPUT, RunState.WAITING_APPROVAL, RunState.TESTING} else RunState.RUNNING)
            return self._public(manifest, self._transition_or_keep(run_id, old_state, target, phase=target.value))
        except TmuxError as error:
            return self._public(manifest, self._transition_or_keep(run_id, old_state, RunState.DISCONNECTED, error=str(error)))

    def stop(self, run_id: str, profile: str | None = None) -> dict[str, Any]:
        """Stop one manifest-owned private session only after ownership validation."""
        manifest, old = self._manifest(run_id, profile), self._status(run_id)
        session, owner = manifest["session"], self._owner(run_id)
        if session != f"cam-{run_id}":
            raise MonitorError("refusing untracked session name")
        try:
            if self.tmux.exists(session):
                if not self.tmux.owned(session, owner):
                    raise MonitorError("refusing to stop unowned session")
                self.tmux.stop(session)
            return self._public(manifest, self._transition_or_keep(run_id, RunState(old["state"]), RunState.STOPPED, phase="stopped"))
        except TmuxError as error:
            raise MonitorError(str(error)) from error

    def show(self, run_id: str, profile: str | None = None) -> dict[str, Any]:
        return self._public(self._manifest(run_id, profile), self._status(run_id))

    def output(self, run_id: str, profile: str | None = None) -> str:
        self._manifest(run_id, profile)
        path = self._paths(run_id)["terminal"]
        return redact_text(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else ""

    def list(self, profile: str | None = None) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for directory in sorted(self.runs.iterdir()):
            if directory.is_dir() and RUN_ID_RE.fullmatch(directory.name):
                try:
                    runs.append(self.show(directory.name, profile))
                except MonitorError:
                    continue
        return runs
