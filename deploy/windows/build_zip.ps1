# Build a portable Windows zip of steadyGrind (onedir PyInstaller).
# Output: dist/latest/steadyGrind-<version>-windows.zip
# Must be run on Windows 11 with uv + Python 3.11+.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"

$Version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$DistDir = Join-Path $Root "dist"
$Latest = Join-Path $DistDir "latest"
$BuildDir = Join-Path $Root "build"
$PyiDist = Join-Path $DistDir "steadyGrind"
$ZipName = "steadyGrind-$Version-windows.zip"
$ZipPath = Join-Path $Latest $ZipName
$Stage = Join-Path $DistDir "windows-stage"

Write-Host "==> Syncing deps (incl. PyInstaller and Bluetooth)…"
uv sync --group dev --extra ble

Write-Host "==> Running required pre-dist tests…"
& "$PSScriptRoot\run_pre_dist_tests.ps1"

Write-Host "==> Ensuring AppIcon.ico…"
& "$PSScriptRoot\make_icon.ps1"

Write-Host "==> Cleaning previous Windows build output…"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $PyiDist, $Stage, (Join-Path $BuildDir "steadygrind")

Write-Host "==> Freezing steadyGrind with PyInstaller…"
uv run pyinstaller `
  --noconfirm `
  --clean `
  --distpath $DistDir `
  --workpath $BuildDir `
  (Join-Path $Root "deploy\windows\steadygrind.spec")

if (-not (Test-Path (Join-Path $PyiDist "steadyGrind.exe"))) {
  throw "expected $PyiDist\steadyGrind.exe after PyInstaller"
}

Write-Host "==> Staging zip contents (v$Version)…"
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Copy-Item -Recurse $PyiDist (Join-Path $Stage "steadyGrind")
Copy-Item (Join-Path $PSScriptRoot "launcher.cmd") (Join-Path $Stage "steadyGrind\Start steadyGrind.cmd")
$ReadMe = (Get-Content (Join-Path $PSScriptRoot "ReadMe.txt") -Raw) -replace "__VERSION__", $Version
Set-Content -Path (Join-Path $Stage "Read Me.txt") -Value $ReadMe -Encoding UTF8

New-Item -ItemType Directory -Force -Path $Latest | Out-Null
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

# Move any previous windows zip in latest to previous-builds
Get-ChildItem $Latest -Filter "steadyGrind-*-windows.zip" -ErrorAction SilentlyContinue | ForEach-Object {
  if ($_.Name -ne $ZipName) {
    $prev = Join-Path $DistDir "previous-builds\$($_.BaseName -replace '^steadyGrind-','' -replace '-windows$','')"
    # Keep simple: archive under previous-builds/<version>/
    $ver = ($_.Name -replace '^steadyGrind-','' -replace '-windows\.zip$','')
    $destDir = Join-Path $DistDir "previous-builds\$ver"
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    Move-Item $_.FullName (Join-Path $destDir $_.Name) -Force
  }
}

Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -Force
Copy-Item (Join-Path $Stage "Read Me.txt") (Join-Path $Latest "WINDOWS_README.txt") -Force
[System.IO.File]::WriteAllText((Join-Path $Latest "VERSION"), "$Version`n")
[System.IO.File]::WriteAllText(
  (Join-Path $Latest "BUILT_AT"),
  ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") + "`n")
)

Write-Host "==> Built: $ZipPath"
Get-Item $ZipPath | Format-List Name, Length, LastWriteTime
