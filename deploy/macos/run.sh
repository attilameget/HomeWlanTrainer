#!/usr/bin/env bash
# Phase A: run steadyGrind on macOS from this repo (port 8080).
# Opens the WebKit window. Running the script again stops the previous
# steadyGrind on port 8080 and loads a fresh page.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${PATH}"

if [[ ! -d .venv ]]; then
  uv venv --python 3.12 .venv
fi

uv sync --extra ble

exec uv run kickr-pi --macos-agent "$@"
