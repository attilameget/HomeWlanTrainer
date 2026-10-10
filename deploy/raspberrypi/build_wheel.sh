#!/usr/bin/env bash
# Build a pure-Python wheel for Raspberry Pi / Debian (and any CPython 3.11+).
# Output: dist/latest/kickr_pi-<version>-py3-none-any.whl
#          dist/latest/PI_INSTALL.md
# A previous dist/latest build moves to dist/previous-builds/<old version>/.
#
# Runs from macOS or Linux. The wheel is platform-agnostic (no native extensions);
# install still happens on the Pi via deploy/raspberrypi/install.sh or pip.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [[ -z "${VERSION}" ]]; then
  echo "error: could not read version from pyproject.toml" >&2
  exit 1
fi

DIST_DIR="${ROOT}/dist"
if [[ -f "${DIST_DIR}/latest/VERSION" ]]; then
  old="$(tr -d '[:space:]' < "${DIST_DIR}/latest/VERSION")"
  if [[ -n "${old}" && "${old}" != "${VERSION}" ]]; then
    mkdir -p "${DIST_DIR}/previous-builds"
    rm -rf "${DIST_DIR}/previous-builds/${old}"
    mv "${DIST_DIR}/latest" "${DIST_DIR}/previous-builds/${old}"
    echo "==> Archived v${old} under dist/previous-builds/${old}"
  fi
fi
VERSION_DIR="${DIST_DIR}/latest"
WHEEL_NAME="kickr_pi-${VERSION}-py3-none-any.whl"
WHEEL_PATH="${VERSION_DIR}/${WHEEL_NAME}"

if [[ "${SKIP_DIST_TESTS:-0}" != "1" ]]; then
  echo "==> Pre-dist tests (unit)…"
  uv run pytest tests -q
else
  echo "==> SKIP_DIST_TESTS=1 — skipping unit suite"
fi

echo "==> Building wheel (v${VERSION})…"
rm -rf "${ROOT}/dist/wheel-scratch"
mkdir -p "${ROOT}/dist/wheel-scratch" "${VERSION_DIR}"
uv build --wheel --out-dir "${ROOT}/dist/wheel-scratch"

BUILT="$(find "${ROOT}/dist/wheel-scratch" -maxdepth 1 -name 'kickr_pi-*-py3-none-any.whl' | head -1)"
if [[ -z "${BUILT}" || ! -f "${BUILT}" ]]; then
  echo "error: wheel not produced under dist/wheel-scratch" >&2
  ls -la "${ROOT}/dist/wheel-scratch" >&2 || true
  exit 1
fi

cp -f "${BUILT}" "${WHEEL_PATH}"
rm -rf "${ROOT}/dist/wheel-scratch"

date -u +'%Y-%m-%dT%H:%M:%SZ' > "${VERSION_DIR}/BUILT_AT_PI"
echo "${VERSION}" > "${VERSION_DIR}/VERSION"

cat > "${VERSION_DIR}/PI_INSTALL.md" <<EOF
# steadyGrind ${VERSION} — Raspberry Pi

Pure-Python wheel for Debian / Raspberry Pi OS (Python 3.11+). Same app as the macOS DMG; no heart-rate BLE on Pi.

## Recommended: install script on the Pi

Clone or copy the repo onto the Pi, then:

\`\`\`bash
cd HomeWlanTrainer
sudo ./deploy/raspberrypi/install.sh
\`\`\`

Details: [deploy/raspberrypi/README.md](../../deploy/raspberrypi/README.md).

## Update from this wheel

On a Pi that already has \`/opt/kickr-pi\`:

\`\`\`bash
sudo /opt/kickr-pi/.venv/bin/pip install --upgrade ./kickr_pi-${VERSION}-py3-none-any.whl
sudo systemctl restart kickr-pi
\`\`\`

Or from the GitHub Release asset:

\`\`\`bash
curl -fL -O https://github.com/attilameget/HomeWlanTrainer/releases/download/v${VERSION}/kickr_pi-${VERSION}-py3-none-any.whl
sudo /opt/kickr-pi/.venv/bin/pip install --upgrade ./kickr_pi-${VERSION}-py3-none-any.whl
sudo systemctl restart kickr-pi
\`\`\`

## Files

- \`${WHEEL_NAME}\` — installable package (\`py3-none-any\`)
- \`PI_INSTALL.md\` — this note
EOF

echo "==> Done: ${WHEEL_PATH}"
ls -lh "${WHEEL_PATH}" "${VERSION_DIR}/PI_INSTALL.md"
