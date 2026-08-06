#!/usr/bin/env bash
# Remove only this monitor's user service, wrapper, and Dashboard adapter.
set -euo pipefail

PROFILE=${1:-coder}
case "$PROFILE" in
  ''|*[!A-Za-z0-9_.-]*) printf '%s\n' 'Invalid profile name.' >&2; exit 2 ;;
esac

HERMES_HOME=$(dirname "$(hermes --profile "$PROFILE" config path)")
PLUGIN_DIR="$HERMES_HOME/plugins/coding-agent-monitor"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_NAME="coding-agent-monitor-${PROFILE}.service"

systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
rm -f "$UNIT_DIR/$UNIT_NAME" "$HOME/.local/bin/coding-agent-monitor"
systemctl --user daemon-reload
hermes --profile "$PROFILE" plugins disable coding-agent-monitor || true
rm -rf "$PLUGIN_DIR/dashboard" "$PLUGIN_DIR/source" "$PLUGIN_DIR/plugin.yaml"
rmdir "$PLUGIN_DIR" 2>/dev/null || true
printf 'Removed coding-agent-monitor service, wrapper, and Dashboard plugin for profile %s.\n' "$PROFILE"
printf 'Run history remains under %s/coding-agent-monitor/runs.\n' "$HERMES_HOME"
printf 'No default tmux sessions were inspected, attached, or stopped.\n'
