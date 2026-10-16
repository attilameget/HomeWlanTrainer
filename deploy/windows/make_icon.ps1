# Build AppIcon.ico from the macOS 256 PNG when Pillow is available.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Out = Join-Path $PSScriptRoot "AppIcon.ico"
$Src = Join-Path $Root "deploy\macos\icon\AppIcon.iconset\icon_256x256.png"

if (Test-Path $Out) {
  Write-Host "AppIcon.ico already present"
  exit 0
}

if (-not (Test-Path $Src)) {
  Write-Host "warning: no source PNG for icon; continuing without .ico"
  exit 0
}

uv run python -c @"
from pathlib import Path
from PIL import Image
src = Path(r'$Src')
out = Path(r'$Out')
img = Image.open(src).convert('RGBA')
sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(out, format='ICO', sizes=sizes)
print('wrote', out)
"@
