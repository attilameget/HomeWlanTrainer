#!/bin/bash
# macOS app entry: start menu-bar agent (which owns the frozen server).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${ROOT}/Resources/steadygrind/steadygrind"

if [[ ! -x "${SERVER}" ]]; then
  osascript -e 'display alert "steadyGrind" message "Missing server binary. Reinstall from the DMG." as critical'
  exit 1
fi

# Fail clearly if port already in use by something that is not us — agent can
# attach when the API already answers; only block unknown listeners.
if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  if ! curl -sf "http://127.0.0.1:8080/api/status" >/dev/null 2>&1; then
    osascript -e 'display alert "steadyGrind" message "Port 8080 is already in use. Quit the other app using that port and try again." as critical'
    exit 1
  fi
fi

export KICKR_HOST="${KICKR_HOST:-0.0.0.0}"
export KICKR_PORT="${KICKR_PORT:-8080}"
export KICKR_TRAINER_MODE="${KICKR_TRAINER_MODE:-dircon}"

# Forward args (e.g. --no-browser from LaunchAgent).
exec "${SERVER}" --macos-agent "$@"
