# Phase A: run steadyGrind on Windows 11 from this repo (port 8080).
# Opens the tray agent and WebView2 window (falls back to the default browser).
# Running the script again stops the previous steadyGrind on port 8080.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"

if (-not (Test-Path ".venv")) {
  uv venv --python 3.12 .venv
}

uv sync --extra ble

uv run steadygrind --windows-agent @args
