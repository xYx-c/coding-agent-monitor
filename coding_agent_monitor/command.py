"""Validate trusted Git worktrees and construct non-bypass agent commands."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ValidationError(ValueError):
    """A requested agent launch parameter is unsafe or invalid."""


def validate_workdir(value: str | Path) -> tuple[Path, str, str]:
    """Require an existing Git worktree with a resolvable branch and HEAD."""
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValidationError("workdir must exist and be a directory")
    try:
        probe = subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], text=True, capture_output=True, timeout=5, check=False)
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, capture_output=True, timeout=5, check=False)
        branch = subprocess.run(["git", "-C", str(path), "branch", "--show-current"], text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError("could not validate git worktree") from error
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        raise ValidationError("workdir must be a git worktree")
    if head.returncode != 0 or not head.stdout.strip():
        raise ValidationError("workdir must have a resolvable HEAD")
    return path, branch.stdout.strip() or "DETACHED", head.stdout.strip()


def build_command(agent: str, workdir: Path) -> list[str]:
    """Build only fixed safe command arguments; no shell or global bypass flags."""
    if agent not in {"claude", "codex"}:
        raise ValidationError(f"unknown agent: {agent}")
    executable = shutil.which(agent)
    if executable is None:
        raise ValidationError(f"agent executable not found: {agent}")
    if agent == "claude":
        return [executable, "--print", "--verbose", "--output-format", "stream-json", "--include-partial-messages", "--permission-mode", "acceptEdits", "--add-dir", str(workdir)]
    return [executable, "exec", "--json", "--sandbox", "workspace-write", "--cd", str(workdir), "--add-dir", str(workdir)]
