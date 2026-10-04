#!/bin/bash
# macOS app entry: start frozen kickr-pi server, open browser, keep running until quit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${ROOT}/Resources/kickr-pi/kickr-pi"
URL="http://127.0.0.1:8080"
LOG_DIR="${HOME}/Library/Logs/steadyGrind"
mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/server.log"

if [[ ! -x "${SERVER}" ]]; then
  osascript -e 'display alert "steadyGrind" message "Missing server binary. Reinstall from the DMG." as critical'
  exit 1
fi

# Fail clearly if port already in use
if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  osascript -e 'display alert "steadyGrind" message "Port 8080 is already in use. Quit the other steadyGrind (or whatever is using that port) and try again." as critical'
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

echo "$(date '+%Y-%m-%dT%H:%M:%S%z') starting steadyGrind" >>"${LOG}"
"${SERVER}" >>"${LOG}" 2>&1 &
SERVER_PID=$!

# Wait until the API answers (or server dies)
ready=0
for _ in $(seq 1 60); do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    osascript -e "display alert \"steadyGrind failed to start\" message \"See log: ${LOG}\" as critical"
    exit 1
  fi
  if curl -sf "${URL}/api/status" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if [[ "${ready}" -ne 1 ]]; then
  osascript -e "display alert \"steadyGrind\" message \"Server did not become ready in time. See ${LOG}\" as critical"
  exit 1
fi

open "${URL}"

# Keep the app "running" so quitting Terminal/Dock stops the server via trap.
# Prefer a LAN IP in the dialog so a phone on the bars can be pointed at the Mac.
LAN_URL=""
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if [[ -n "${LAN_IP}" ]]; then
  LAN_URL="http://${LAN_IP}:8080"
fi

osascript >/dev/null 2>&1 <<EOF || true
tell application "System Events" to set frontmost of process "steadyGrind" to true
display dialog "steadyGrind is running at http://127.0.0.1:8080${LAN_URL:+
Phone on the same Wi‑Fi: ${LAN_URL}}

Allow Local Network access if macOS asks (needed to find the KICKR).

Click Quit when you are done riding." buttons {"Quit"} default button "Quit" with title "steadyGrind" giving up after 86400
EOF

exit 0
