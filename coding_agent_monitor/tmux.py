"""A narrow tmux adapter that can only use the monitor's private socket."""

from __future__ import annotations

import hmac
import subprocess
from pathlib import Path

SOCKET = "hermes-coding"
OWNER_OPTION = "@coding_agent_monitor_owner"


class TmuxError(RuntimeError):
    """tmux was unavailable, timed out, or refused an expected command."""


class TmuxClient:
    """All operations explicitly use ``tmux -L hermes-coding``."""

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(["tmux", "-L", SOCKET, *args], text=True, capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TmuxError("tmux unavailable or timed out") from error
        if check and result.returncode != 0:
            raise TmuxError("private tmux command failed")
        return result

    def create(self, session: str, script: Path, owner: str) -> None:
        """Create a private session, mark ownership, then retain output after exit."""
        wrapper = f"{script} || code=$?; printf '\\n[monitor agent exit=%s]\\n' \"${{code:-0}}\"; exec sleep 2147483647"
        self._run(["new-session", "-d", "-s", session, "sh", "-c", "exec sleep 2147483647"])
        try:
            self._run(["set-option", "-q", "-t", session, OWNER_OPTION, owner])
            self._run(["respawn-pane", "-k", "-t", session, "sh", "-c", wrapper])
        except TmuxError:
            self._run(["kill-session", "-t", session], check=False)
            raise

    def exists(self, session: str) -> bool:
        return self._run(["has-session", "-t", session], check=False).returncode == 0

    def owned(self, session: str, owner: str) -> bool:
        result = self._run(["show-options", "-qv", "-t", session, OWNER_OPTION], check=False)
        return result.returncode == 0 and hmac.compare_digest(result.stdout.strip(), owner)

    def capture(self, session: str) -> str:
        return self._run(["capture-pane", "-p", "-e", "-t", session]).stdout

    def stop(self, session: str) -> None:
        self._run(["kill-session", "-t", session])
