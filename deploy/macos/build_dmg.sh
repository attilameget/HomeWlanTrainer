#!/usr/bin/env bash
# Build KICKR Pi.app and pack it into a drag-and-drop DMG.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [[ -z "${VERSION}" ]]; then
  echo "error: could not read version from pyproject.toml" >&2
  exit 1
fi
APP_NAME="KICKR Pi"
DIST_DIR="${ROOT}/dist"
APP_DIR="${DIST_DIR}/${APP_NAME}.app"
DMG_NAME="KICKR-Pi-${VERSION}-macos.dmg"
DMG_PATH="${DIST_DIR}/${DMG_NAME}"
STAGE="${DIST_DIR}/dmg-stage"
VOL_NAME="KICKR Pi ${VERSION}"

"${ROOT}/deploy/macos/build_app.sh"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "error: app missing at ${APP_DIR}" >&2
  exit 1
fi

echo "==> Staging DMG contents…"
rm -rf "${STAGE}"
mkdir -p "${STAGE}"
cp -R "${APP_DIR}" "${STAGE}/"
cp "${ROOT}/deploy/macos/ReadMe.txt" "${STAGE}/Read Me.txt"
ln -s /Applications "${STAGE}/Applications"

# Clear any previous DMG
rm -f "${DMG_PATH}" "${DIST_DIR}/rw.${DMG_NAME}"

echo "==> Creating ${DMG_NAME}…"
# Create a read/write UDIF, then convert to compressed read-only
hdiutil create \
  -volname "${VOL_NAME}" \
  -srcfolder "${STAGE}" \
  -ov \
  -format UDRW \
  "${DIST_DIR}/rw.${DMG_NAME}"

hdiutil convert \
  "${DIST_DIR}/rw.${DMG_NAME}" \
  -format ULMO \
  -o "${DMG_PATH}"

rm -f "${DIST_DIR}/rw.${DMG_NAME}"
rm -rf "${STAGE}"

echo "==> Done: ${DMG_PATH}"
ls -lh "${DMG_PATH}"
