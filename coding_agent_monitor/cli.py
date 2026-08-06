"""CLI for explicit monitor start, observation, stop, and loopback service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .server import serve
from .service import MonitorError, Supervisor


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coding-agent-monitor", allow_abbrev=False)
    parser.add_argument("--home", help="override HERMES_HOME for monitor data")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", allow_abbrev=False)
    start.add_argument("--agent", choices=("claude", "codex"), required=True)
    start.add_argument("--workdir", required=True)
    task_source = start.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task-file", help="owner-readable regular task file")
    task_source.add_argument("--task-stdin", action="store_true", help="read task from standard input")
    start.add_argument("--profile", default="default")
    for name in ("list",):
        command = sub.add_parser(name, allow_abbrev=False)
        command.add_argument("--profile", default="default")
    for name in ("show", "refresh"):
        command = sub.add_parser(name, allow_abbrev=False)
        command.add_argument("id")
        command.add_argument("--profile", default="default")
    stop = sub.add_parser("stop", allow_abbrev=False)
    stop.add_argument("id")
    stop.add_argument("--profile", default="default")
    stop.add_argument("--yes", action="store_true", help="confirm stopping only this known run")
    server = sub.add_parser("serve", allow_abbrev=False)
    server.add_argument("--profile", default="default")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=0)
    return parser


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))


def main(argv: list[str] | None = None) -> int:
    """Run one explicit operation. Stop is deliberately non-interactive and opt-in."""
    args = _parser().parse_args(argv)
    supervisor = Supervisor(Path(args.home) if args.home else None)
    try:
        if args.command == "start":
            if args.task_stdin:
                task = sys.stdin.read()
            else:
                task_path = Path(args.task_file).expanduser()
                if task_path.is_symlink() or not task_path.is_file():
                    raise MonitorError("task file must be a regular file")
                task = task_path.read_text(encoding="utf-8")
            _print(supervisor.start(args.agent, args.workdir, task, args.profile))
        elif args.command == "list":
            _print({"runs": supervisor.list(args.profile)})
        elif args.command == "show":
            _print(supervisor.show(args.id, args.profile))
        elif args.command == "refresh":
            _print(supervisor.refresh(args.id, args.profile))
        elif args.command == "stop":
            if not args.yes:
                raise MonitorError("stop requires --yes")
            _print(supervisor.stop(args.id, args.profile))
        else:
            server = serve(supervisor, args.profile, args.host, args.port)
            print(f"serving on http://{server.server_address[0]}:{server.server_address[1]}", file=sys.stderr)
            server.serve_forever()
        return 0
    except MonitorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
