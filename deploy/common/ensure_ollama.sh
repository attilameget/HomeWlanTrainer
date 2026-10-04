#!/usr/bin/env bash
# Ensure Ollama is installed and reachable for steadyGrind plan sketches.
#
# Usage:
#   ./deploy/common/ensure_ollama.sh           # prints status; exit 0 = ready
#   eval "$(./deploy/common/ensure_ollama.sh --emit-env)"
#
# On success: Ollama CLI present, API up, default model pulled → feature ON.
# On failure: leaves the system as-is → feature OFF (caller toggles settings).
set -euo pipefail

EMIT_ENV=0
SKIP_PULL=0
MODEL="${KICKR_OLLAMA_MODEL:-}"
BASE_URL="${KICKR_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --emit-env) EMIT_ENV=1; shift ;;
    --skip-pull) SKIP_PULL=1; shift ;;
    --model) MODEL="${2:?}"; shift 2 ;;
    --base-url) BASE_URL="${2:?}"; shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

log() { echo "==> $*" >&2; }
fail() {
  log "Ollama not ready — plan LLM feature will stay OFF ($*)"
  if [[ "${EMIT_ENV}" -eq 1 ]]; then
    echo "export KICKR_OLLAMA_ENABLED=false"
  fi
  exit 1
}

pick_model() {
  if [[ -n "${MODEL}" ]]; then
    echo "${MODEL}"
    return
  fi
  # ~8B needs comfortable headroom; small hosts get a 3B default
  local mem_gb=0
  if [[ "$(uname -s)" == "Darwin" ]]; then
    local bytes
    bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    mem_gb=$((bytes / 1024 / 1024 / 1024))
  elif [[ -r /proc/meminfo ]]; then
    local kb
    kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
    mem_gb=$((kb / 1024 / 1024))
  fi
  if [[ "${mem_gb}" -ge 16 ]]; then
    echo "llama3.1:8b"
  else
    echo "llama3.2:3b"
  fi
}

MODEL="$(pick_model)"

api_up() {
  curl -sf --max-time 3 "${BASE_URL%/}/api/tags" >/dev/null 2>&1
}

have_cli() {
  command -v ollama >/dev/null 2>&1
}

start_server() {
  if api_up; then
    return 0
  fi
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if [[ -d "/Applications/Ollama.app" ]]; then
      log "Starting Ollama.app…"
      open -a Ollama >/dev/null 2>&1 || true
    elif have_cli; then
      log "Starting ollama serve…"
      nohup ollama serve >/tmp/steadygrind-ollama.log 2>&1 &
    fi
  else
    if command -v systemctl >/dev/null 2>&1; then
      systemctl start ollama.service >/dev/null 2>&1 || true
      systemctl enable ollama.service >/dev/null 2>&1 || true
    fi
    if have_cli && ! api_up; then
      log "Starting ollama serve…"
      nohup ollama serve >/tmp/steadygrind-ollama.log 2>&1 &
    fi
  fi
  local i
  for i in $(seq 1 30); do
    if api_up; then
      return 0
    fi
    sleep 1
  done
  return 1
}

install_ollama() {
  log "Installing Ollama…"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install ollama >/dev/null 2>&1 || brew install --cask ollama >/dev/null 2>&1 || true
    fi
    if have_cli || [[ -d "/Applications/Ollama.app" ]]; then
      return 0
    fi
  fi
  # Official installer (Linux + macOS fallback)
  if ! command -v curl >/dev/null 2>&1; then
    return 1
  fi
  curl -fsSL https://ollama.com/install.sh | sh
}

pull_model() {
  if [[ "${SKIP_PULL}" -eq 1 ]]; then
    return 0
  fi
  log "Pulling model ${MODEL} (may take a while)…"
  ollama pull "${MODEL}"
}

# --- main ---
if ! have_cli && [[ ! -d "/Applications/Ollama.app" ]]; then
  install_ollama || fail "install failed"
fi

# Refresh PATH after install
export PATH="/usr/local/bin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH}"

if ! have_cli && [[ ! -d "/Applications/Ollama.app" ]]; then
  fail "ollama CLI / app still missing after install"
fi

start_server || fail "API not reachable at ${BASE_URL}"

if have_cli; then
  pull_model || fail "could not pull ${MODEL}"
else
  log "Ollama.app present but CLI missing — skipping model pull; enable after installing CLI"
fi

log "Ollama ready (model=${MODEL})"
if [[ "${EMIT_ENV}" -eq 1 ]]; then
  echo "export KICKR_OLLAMA_ENABLED=true"
  echo "export KICKR_OLLAMA_BASE_URL=$(printf '%q' "${BASE_URL}")"
  echo "export KICKR_OLLAMA_MODEL=$(printf '%q' "${MODEL}")"
fi
exit 0
