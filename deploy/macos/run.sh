#!/usr/bin/env bash
# Phase A: run steadyGrind on macOS (port 8080).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"

if [[ ! -d .venv ]]; then
  uv venv --python 3.12 .venv
fi

uv sync
exec uv run kickr-pi
