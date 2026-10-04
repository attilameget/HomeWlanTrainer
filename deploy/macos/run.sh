#!/usr/bin/env bash
# Phase A: run steadyGrind on macOS (port 8080).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${PATH}"

if [[ ! -d .venv ]]; then
  uv venv --python 3.12 .venv
fi

uv sync

# Optional local LLM for training plans: install Ollama when missing.
# If install/API fails, keep the feature OFF (rules generator still works).
ENSURE="${ROOT}/deploy/common/ensure_ollama.sh"
if [[ -x "${ENSURE}" ]]; then
  set +e
  eval "$("${ENSURE}" --emit-env)"
  set -e
fi
export KICKR_OLLAMA_ENABLED="${KICKR_OLLAMA_ENABLED:-false}"

exec uv run kickr-pi
