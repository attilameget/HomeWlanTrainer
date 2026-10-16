# Unit + e2e tests required before a Windows dist build.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"

Write-Host "==> Unit tests…"
uv run pytest -q

Write-Host "==> E2E (Playwright / Emulator)…"
uv sync --group dev
uv run playwright install chromium
uv run pytest e2e -q
