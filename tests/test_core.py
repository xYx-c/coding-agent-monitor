from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_agent_monitor.command import ValidationError, build_command, validate_workdir
from coding_agent_monitor.redaction import redact_text
from coding_agent_monitor.service import MonitorError, Supervisor


class FakeTmux:
    def __init__(self) -> None:
        self.sessions: dict[str, str] = {}
        self.output = ""
        self.stopped: list[str] = []

    def create(self, session: str, _script: Path, owner: str) -> None:
        self.sessions[session] = owner

    def exists(self, session: str) -> bool:
        return session in self.sessions

    def owned(self, session: str, owner: str) -> bool:
        return self.sessions.get(session) == owner

    def capture(self, _session: str) -> str:
        return self.output

    def stop(self, session: str) -> None:
        self.stopped.append(session)
        self.sessions.pop(session)


class CoreTests(unittest.TestCase):
    def test_redaction_handles_wrapped_assignment(self) -> None:
        value = redact_text("api_key=do-not-\npersist-987654321")
        self.assertNotIn("do-not-persist", value)
        self.assertNotIn("persist-987654321", value)
        self.assertIn("[REDACTED]", value)

    def test_command_has_no_dangerous_bypass(self) -> None:
        with patch("coding_agent_monitor.command.shutil.which", return_value="/bin/codex"):
            command = build_command("codex", Path("/work"))
        self.assertIn("workspace-write", command)
        self.assertNotIn("dangerously", " ".join(command))

    def test_workdir_requires_real_git_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationError):
                validate_workdir(tmp)
            root = Path(tmp) / "repo"
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            (root / "a").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "a"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
            _path, _branch, head = validate_workdir(root)
            self.assertEqual(len(head), 40)

    def test_stop_requires_profile_and_matching_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmux = FakeTmux()
            supervisor = Supervisor(tmp, tmux)
            with patch("coding_agent_monitor.service.validate_workdir", return_value=(Path(tmp), "main", "a" * 40)), patch("coding_agent_monitor.service.build_command", return_value=["/bin/true"]):
                run = supervisor.start("claude", tmp, "test task", "coder")
            run_id = run["manifest"]["run_id"]
            with self.assertRaises(MonitorError):
                supervisor.stop(run_id, "other")
            tmux.sessions[f"cam-{run_id}"] = "wrong"
            with self.assertRaises(MonitorError):
                supervisor.stop(run_id, "coder")
            self.assertEqual(tmux.stopped, [])


if __name__ == "__main__":
    unittest.main()
