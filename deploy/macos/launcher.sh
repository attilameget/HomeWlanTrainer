#!/bin/bash
# macOS app entry: start frozen kickr-pi, open browser, keep running until quit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${ROOT}/Resources/kickr-pi/kickr-pi"
URL="http://127.0.0.1:8080"
LOG_DIR="${HOME}/Library/Logs/KICKR-Pi"
mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/server.log"

if [[ ! -x "${SERVER}" ]]; then
  osascript -e 'display alert "KICKR Pi" message "Missing server binary. Reinstall from the DMG." as critical'
  exit 1
fi

# Fail clearly if port already in use
if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  osascript -e 'display alert "KICKR Pi" message "Port 8080 is already in use. Quit the other KICKR Pi (or whatever is using that port) and try again." as critical'
  exit 1
fi

export KICKR_HOST="${KICKR_HOST:-0.0.0.0}"
export KICKR_PORT="${KICKR_PORT:-8080}"
export KICKR_TRAINER_MODE="${KICKR_TRAINER_MODE:-dircon}"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "$(date '+%Y-%m-%dT%H:%M:%S%z') starting KICKR Pi" >>"${LOG}"
"${SERVER}" >>"${LOG}" 2>&1 &
SERVER_PID=$!

# Wait until the API answers (or server dies)
ready=0
for _ in $(seq 1 60); do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    osascript -e "display alert \"KICKR Pi failed to start\" message \"See log: ${LOG}\" as critical"
    exit 1
  fi
  if curl -sf "${URL}/api/status" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if [[ "${ready}" -ne 1 ]]; then
  osascript -e "display alert \"KICKR Pi\" message \"Server did not become ready in time. See ${LOG}\" as critical"
  exit 1
fi

open "${URL}"

# Keep the app "running" so quitting Terminal/Dock stops the server via trap.
# Show a tiny stay-open dialog; Cancel/OK both quit after user closes it.
osascript <<'EOF' >/dev/null 2>&1 || true
tell application "System Events" to set frontmost of process "KICKR Pi" to true
display dialog "KICKR Pi is running at http://127.0.0.1:8080

Allow Local Network access if macOS asks (needed to find the KICKR).

Click Quit when you are done riding." buttons {"Quit"} default button "Quit" with title "KICKR Pi" giving up after 86400
EOF

exit 0
