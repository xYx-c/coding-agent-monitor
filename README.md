# Coding Agent Monitor

[中文说明](README.zh-CN.md) · A standalone local supervisor for **Claude Code** and **Codex**, with an opt-in [Hermes Agent](https://hermes-agent.nousresearch.com/docs) Dashboard plugin.

It gives coding agents a safe, observable execution surface without patching Hermes core or sharing your ordinary tmux server.

> **Status:** usable local operator tool. It has real Claude/Codex command adapters, private tmux isolation, profile-scoped state, a loopback API, read-only Dashboard output, and explicit stop confirmation. It is intentionally not a replacement for interactive terminal sessions or a remote multi-user service.

## What it does

- Launches each run in the dedicated `tmux -L hermes-coding` socket, never in bare/default `tmux`.
- Accepts only existing Git worktrees with a resolvable commit; records the launch branch and HEAD.
- Runs Claude Code in structured `stream-json` mode and Codex in structured `--json` mode.
- Stores profile-scoped run status, a bounded event tail, and a read-only ANSI snapshot.
- Provides a token-protected API on loopback only; the Dashboard adapter keeps that token on the server side.
- Adds a **Coding Agents** Dashboard page for starting, observing, refreshing, viewing read-only output, and explicitly stopping one known run.
- Keeps the full source checkout at the user-level Hermes plugin location after installation, rather than relying on `/root/coding-agent-monitor`.

## Safety contract

| Boundary | Behaviour |
| --- | --- |
| Hermes core | Does **not** modify `/usr/local/lib/hermes-agent`, Dashboard bundles, the native TUI, or Hermes configuration files. |
| tmux | Every monitor call contains `tmux -L hermes-coding`; there is no bare `tmux`, `kill-server`, `pkill tmux`, attach, or cleanup operation. |
| Stop | A stop targets one generated `cam-<run-id>` session and additionally requires its random ownership marker. CLI needs `--yes`; the API/Dashboard need `confirm: true`. |
| Network | Supervisor accepts only `127.0.0.1`, `::1`, or `localhost`; it is not a LAN listener. |
| Agent permissions | Claude receives `--permission-mode acceptEdits`; Codex receives `--sandbox workspace-write`. No global bypass flag is added. |
| Profiles | Listing, show, output, refresh, and stop require the owning Hermes profile. |
| Tasks & records | CLI tasks come from stdin or a regular task file, not process arguments. Original task text is not deliberately persisted in the run manifest or API metadata. |
| Secrets | Transcript/events/API payloads are redacted before persistence or response. This is defense in depth—do not deliberately paste credentials into tasks or commands. |

## Requirements

- Linux with a user systemd session (`systemctl --user`)
- Hermes Agent with Dashboard plugins available
- `uv`, `git`, `tmux`
- Claude Code (`claude`) and/or Codex (`codex`) on the service `PATH`
- A Git worktree you explicitly trust the selected agent to edit

The standalone package has no third-party Python dependency. The Dashboard adapter uses the Python dependencies shipped with Hermes.

## Install

Clone anywhere temporarily, then install once. The installer copies a clean source checkout into the target profile's plugin directory; after success, `/root/coding-agent-monitor` is no longer the runtime source of truth.

```bash
git clone https://github.com/xYx-c/coding-agent-monitor.git /tmp/coding-agent-monitor
cd /tmp/coding-agent-monitor
./install.sh coder
```

The installer:

1. copies the full project to:
   ```text
   <profile-home>/plugins/coding-agent-monitor/source
   ```
2. copies the slim Dashboard adapter to:
   ```text
   <profile-home>/plugins/coding-agent-monitor/dashboard
   ```
3. installs `~/.local/bin/coding-agent-monitor`, a wrapper that runs that profile-local source with `uv`;
4. creates and enables `coding-agent-monitor-<profile>.service`; and
5. enables the user-level Hermes plugin.

The profile home is obtained through `hermes --profile <name> config path`; for `coder`, it is normally `~/.hermes/profiles/coder`.

Restart a running Dashboard process after installation, then open/reload **Coding Agents** (`/coding-agents`):

```bash
hermes --profile coder dashboard
```

### Upgrade

Run the installer again from a newer checked-out revision. It stages a clean source copy before replacing the installed source, restarts the user service, and recopies the Dashboard adapter. It does **not** delete run history.

```bash
cd /path/to/new/coding-agent-monitor
./install.sh coder
```

### Service operations

```bash
systemctl --user status coding-agent-monitor-coder.service
systemctl --user restart coding-agent-monitor-coder.service
journalctl --user -u coding-agent-monitor-coder.service -f
```

The endpoint and bearer token are generated per profile below:

```text
<profile-home>/coding-agent-monitor/profiles/<profile>/
```

They are private local implementation details. Do not copy the token into a browser, shell history, repository, or issue tracker.

## Everyday CLI use

The normal wrapper is available after installation:

```bash
# Claude task: stdin keeps task text out of the process argument list.
printf '%s\n' 'Inspect the failing tests and make the smallest safe repair.' \
  | coding-agent-monitor start \
      --agent claude \
      --workdir /absolute/path/to/trusted/git-worktree \
      --task-stdin \
      --profile coder

# Codex task:
printf '%s\n' 'Implement the requested change and run focused tests.' \
  | coding-agent-monitor start \
      --agent codex \
      --workdir /absolute/path/to/trusted/git-worktree \
      --task-stdin \
      --profile coder

# An owner-readable regular file is also supported:
coding-agent-monitor start \
  --agent claude \
  --workdir /absolute/path/to/trusted/git-worktree \
  --task-file /secure/path/task.txt \
  --profile coder
```

Then inspect one run and stop it only deliberately:

```bash
coding-agent-monitor list --profile coder
coding-agent-monitor show <run-id> --profile coder
coding-agent-monitor refresh <run-id> --profile coder
coding-agent-monitor stop <run-id> --profile coder --yes
```

`start` refuses non-Git directories, unresolvable HEADs, unknown agents, missing executables, empty tasks, and unsafe task-file types. The monitor does **not** make a dirty worktree clean or decide whether an agent's edits should be committed; that responsibility remains with the operator.

## Dashboard workflow

1. Open the **Coding Agents** tab in a Dashboard process running the same profile.
2. Select Claude Code or Codex.
3. Enter an absolute path to a trusted Git worktree and the task.
4. Select **Start isolated run**.
5. Refresh or expand a run to read its status, metadata, events, and **read-only** terminal capture.
6. Use the single-run stop action only after its confirmation dialog.

Closing the Dashboard stops observation only. It does not stop a coding agent. There is no keystroke injection or interactive shell in the page by design.

## Persisted data

Per-profile operational data lives outside the plugin source tree:

```text
<profile-home>/coding-agent-monitor/
├── profiles/<profile>/
│   ├── api.token        # 0600; do not disclose
│   └── endpoint.json    # local loopback address only
└── runs/<run-id>/
    ├── manifest.json    # agent/worktree/branch/HEAD, task summary only
    ├── status.json
    ├── events.jsonl     # redacted event tail/history
    ├── terminal.ansi    # redacted read-only capture
    ├── ownership.token  # 0600 ownership guard
    └── launch.sh        # transient task-file path; not task text
```

The task file itself is created with mode `0600`, preferably under `/dev/shm`, passed to the agent on stdin, and removed by the launch script when the agent exits. Redaction is intentionally an extra barrier, not authorization to expose secrets.

## Remove

Run the installed script (or the source checkout used for installation):

```bash
~/.hermes/profiles/coder/plugins/coding-agent-monitor/source/uninstall.sh coder
```

Removal disables/removes only this monitor's user service, wrapper, adapter, and installed source. It **retains** `coding-agent-monitor/runs` under the profile home for deliberate review. Remove that history yourself only when you have decided it is no longer needed.

No default tmux session is listed, attached, modified, or stopped during uninstall.

## Development & verification

```bash
cd /path/to/coding-agent-monitor
bash -n install.sh uninstall.sh
uv run python -m compileall -q coding_agent_monitor dashboard_plugin/dashboard/plugin_api.py
uv run python -m unittest discover -s tests -v
```

The test suite covers command safety, state transitions, worktree validation, profile isolation, task non-persistence, redaction, loopback API authentication, stop confirmation, plugin manifest/API proxy guards, and an integration check proving a private-socket run does not alter the default tmux server.

For the Dashboard proxy tests, run the small launcher with Hermes's runtime Python because FastAPI/Pydantic belong to Hermes rather than the standalone supervisor environment:

```bash
cd tests
/usr/local/lib/hermes-agent/venv/bin/python run_plugin_runtime.py
```

`tests/run_plugin_runtime.py` is intentionally ignored: it is an environment-specific verification helper, not shipped program code.

## Scope and limitations

- This is **not** a native Hermes TUI `/agents` integration. Doing that would modify Hermes core; the Dashboard plugin is the upgrade-safe integration surface.
- Agent status reflects process/structured-output observation, not a claim that generated code or tests are correct.
- The ANSI capture is a snapshot of visible pane output, not a full terminal recorder.
- The project intentionally avoids remote control, LAN binding, shared multi-user queues, arbitrary tmux targets, and interactive terminal injection.

## License

No license has been selected yet. Add one before redistributing the project outside the intended private repository.

## Security reporting

For a suspected secret leak or unsafe stop/isolation behavior, do not paste credentials into a public issue. Disable the service first, preserve only redacted evidence, and report the reproduction path privately to the repository owner.

```bash
systemctl --user disable --now coding-agent-monitor-coder.service
```

This command stops only the monitor's own user service; it does not affect your normal tmux server.
