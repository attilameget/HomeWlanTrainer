#!/usr/bin/env bash
# Assemble steadyGrind.app from a PyInstaller onedir build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"

APP_NAME="steadyGrind"
DIST_DIR="${ROOT}/dist"
BUILD_DIR="${ROOT}/build"
APP_DIR="${DIST_DIR}/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
PYI_DIST="${DIST_DIR}/kickr-pi"

echo "==> Syncing deps (incl. PyInstaller and Bluetooth heart rate)…"
uv sync --group dev --extra ble

echo "==> Running required pre-dist tests…"
"${ROOT}/deploy/macos/run_pre_dist_tests.sh"

echo "==> Cleaning previous app / pyinstaller output…"
rm -rf "${APP_DIR}" "${PYI_DIST}" "${BUILD_DIR}/kickr-pi" "${DIST_DIR}/kickr-pi"

echo "==> Freezing kickr-pi with PyInstaller…"
uv run pyinstaller \
  --noconfirm \
  --clean \
  --distpath "${DIST_DIR}" \
  --workpath "${BUILD_DIR}" \
  "${ROOT}/deploy/macos/kickr-pi.spec"

if [[ ! -x "${PYI_DIST}/kickr-pi" ]]; then
  echo "error: expected ${PYI_DIST}/kickr-pi after PyInstaller" >&2
  exit 1
fi

VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
echo "==> Assembling ${APP_NAME}.app (v${VERSION})…"
mkdir -p "${MACOS_DIR}" "${RESOURCES}"

# Frozen server lives under Resources so the Mach-O launcher stays tiny
cp -R "${PYI_DIST}" "${RESOURCES}/kickr-pi"
cp "${ROOT}/deploy/macos/AppIcon.icns" "${RESOURCES}/AppIcon.icns"

install -m 0755 "${ROOT}/deploy/macos/launcher.sh" "${MACOS_DIR}/steadyGrind"
# Stamp version from pyproject.toml into the bundle Info.plist
sed -E \
  -e "s|(<key>CFBundleShortVersionString</key>[[:space:]]*<string>)[^<]+|\1${VERSION}|" \
  -e "s|(<key>CFBundleVersion</key>[[:space:]]*<string>)[^<]+|\1${VERSION}|" \
  "${ROOT}/deploy/macos/Info.plist" > "${CONTENTS}/Info.plist"

# PkgInfo (optional but conventional)
printf 'APPL????' > "${CONTENTS}/PkgInfo"

echo "==> Built: ${APP_DIR}"
du -sh "${APP_DIR}"
