#!/usr/bin/env bash
# Run unit + UI e2e tests before packaging a distribution build.
# Set SKIP_DIST_TESTS=1 to bypass (not recommended).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"

if [[ "${SKIP_DIST_TESTS:-}" == "1" ]]; then
  echo "==> SKIP_DIST_TESTS=1 — skipping pre-dist tests"
  exit 0
fi

echo "==> Pre-dist tests: unit suite…"
uv run pytest -q

echo "==> Pre-dist tests: UI e2e (Emulator)…"
# Ensure Chromium is available for Playwright (no-op if already installed)
uv run playwright install chromium >/dev/null
uv run pytest e2e -q

echo "==> Pre-dist tests passed"
