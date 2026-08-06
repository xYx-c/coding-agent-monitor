#!/usr/bin/env bash
# Install only this standalone monitor and its user-level Dashboard plugin.
# Hermes core files and the default tmux socket are never modified.
set -euo pipefail

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE=${1:-coder}
case "$PROFILE" in
  ''|*[!A-Za-z0-9_.-]*) printf '%s\n' 'Invalid profile name.' >&2; exit 2 ;;
esac

HERMES_HOME=$(dirname "$(hermes --profile "$PROFILE" config path)")
PLUGIN_DIR="$HERMES_HOME/plugins/coding-agent-monitor"
# The full standalone repository lives here. This is intentionally separate
# from the lightweight Hermes plugin adapter under "$PLUGIN_DIR/dashboard".
PROJECT_DIR="$PLUGIN_DIR/source"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_NAME="coding-agent-monitor-${PROFILE}.service"
WRAPPER_DIR="$HOME/.local/bin"

if [ "$SOURCE_DIR" != "$PROJECT_DIR" ]; then
  install -d -m 700 "$PLUGIN_DIR"
  stage=$(mktemp -d "${TMPDIR:-/tmp}/coding-agent-monitor.XXXXXX")
  cleanup() { rm -rf -- "$stage"; }
  trap cleanup EXIT HUP INT TERM
  cp -a "$SOURCE_DIR/." "$stage/source"
  rm -rf "$stage/source/.venv" "$stage/source/.pytest_cache" \
    "$stage/source/coding_agent_monitor.egg-info" "$stage/source/runs"
  rm -f "$stage/source/tests/run_plugin_runtime.py"
  find "$stage/source" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "$stage/source" -type f \( -name '*.ansi' -o -name '*.jsonl' -o -name 'api.token' -o -name 'endpoint.json' \) -delete
  rm -rf "$PROJECT_DIR"
  # Keep the Git metadata: the installed source directory is the canonical
  # user-level checkout, so it can be updated without retaining a /root copy.
  mv "$stage/source" "$PROJECT_DIR"
  trap - EXIT HUP INT TERM
  rmdir "$stage" 2>/dev/null || true
fi

install -d -m 700 "$PROJECT_DIR" "$PLUGIN_DIR/dashboard" "$UNIT_DIR" "$WRAPPER_DIR"
rm -rf "$PLUGIN_DIR/dashboard"
install -d -m 700 "$PLUGIN_DIR/dashboard"
cp -R "$PROJECT_DIR/dashboard_plugin/dashboard/." "$PLUGIN_DIR/dashboard/"
cp "$PROJECT_DIR/dashboard_plugin/plugin.yaml" "$PLUGIN_DIR/plugin.yaml"
find "$PROJECT_DIR" -type d -exec chmod 700 {} +
find "$PROJECT_DIR" -type f -exec chmod 600 {} +
find "$PLUGIN_DIR/dashboard" -type d -exec chmod 700 {} +
find "$PLUGIN_DIR/dashboard" -type f -exec chmod 600 {} +
chmod 700 "$PROJECT_DIR/install.sh" "$PROJECT_DIR/uninstall.sh"

cat > "$WRAPPER_DIR/coding-agent-monitor" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec uv run --project "$PROJECT_DIR" python -m coding_agent_monitor "\$@"
EOF
chmod 755 "$WRAPPER_DIR/coding-agent-monitor"

cat > "$UNIT_DIR/$UNIT_NAME" <<EOF
[Unit]
Description=Standalone local coding-agent monitor for Hermes profile $PROFILE
After=default.target

[Service]
Type=simple
Environment=HERMES_HOME=$HERMES_HOME
Environment=HERMES_PROFILE=$PROFILE
Environment=HOME=$HOME
Environment=PATH=$HOME/.local/bin:/root/.local/bin:$HOME/.hermes/node/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$WRAPPER_DIR/coding-agent-monitor serve --profile $PROFILE --host 127.0.0.1 --port 0
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes

[Install]
WantedBy=default.target
EOF
chmod 600 "$UNIT_DIR/$UNIT_NAME"

systemctl --user daemon-reload
systemctl --user enable "$UNIT_NAME"
systemctl --user restart "$UNIT_NAME"
hermes --profile "$PROFILE" plugins enable coding-agent-monitor --no-allow-tool-override

printf 'Installed coding-agent-monitor for profile %s.\n' "$PROFILE"
printf 'Dashboard restart/reload is required before the new plugin API routes mount.\n'
printf 'Status: systemctl --user status %s\n' "$UNIT_NAME"
printf 'Uninstall: %s/uninstall.sh %s\n' "$PROJECT_DIR" "$PROFILE"
