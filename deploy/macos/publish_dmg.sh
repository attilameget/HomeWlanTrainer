#!/usr/bin/env bash
# One-shot: build + commit + push the versioned macOS DMG for the current pyproject version.
# Must run on macOS (Darwin) with hdiutil. Example:
#   git checkout cursor/add-kickr-spec && git pull
#   ./deploy/macos/publish_dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: publish_dmg.sh requires macOS (found $(uname -s))" >&2
  exit 1
fi
if ! command -v hdiutil >/dev/null 2>&1; then
  echo "error: hdiutil not found" >&2
  exit 1
fi

VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
DMG="dist/${VERSION}/steadyGrind-${VERSION}-macos.dmg"

"${ROOT}/deploy/macos/build_dmg.sh"

if [[ ! -f "${DMG}" ]]; then
  echo "error: missing ${DMG}" >&2
  exit 1
fi

# Restore download docs to match prior release style
python3 - <<'PY'
from pathlib import Path
import re
ver = None
for line in Path("pyproject.toml").read_text().splitlines():
    m = re.match(r'version\s*=\s*"([^"]+)"', line)
    if m:
        ver = m.group(1)
        break
assert ver
what = Path(f"dist/{ver}/WHAT_IS_NEW.md")
what.write_text(
    f"""# What's new in {ver}

Released **2026-10-04**. Full project history: [CHANGELOG.md](../../CHANGELOG.md).

## Highlights

- **Plan.** New Plan screen builds an on-host bike+run calendar from FTP, saved rides, and Garmin history. Bike days are ERG-playable; run days are guidance; optional Sync to Garmin.
- **Claude sketches.** With an Anthropic API key on Plan (collapsed settings), generate with Claude (`claude-sonnet-5-5` default); otherwise rules-based. Keys never leave your machine via settings responses.
- **Week ahead.** After a saved ride of 30+ minutes, the next week starting tomorrow can refresh automatically.
- Same-day bike+run doubles so requested high day counts are honored.

## Installer

- `steadyGrind-{ver}-macos.dmg` (this folder)
- GitHub Release: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v{ver}
"""
)
readme = Path("README.md").read_text()
block = f"""## Share with a friend (macOS DMG installer)

**Download the latest DMG** (Apple silicon, v{ver}):

```bash
curl -fL -o steadyGrind-{ver}-macos.dmg \\
  https://github.com/attilameget/HomeWlanTrainer/releases/download/v{ver}/steadyGrind-{ver}-macos.dmg
```

Also in the repo: [`dist/{ver}/`](dist/{ver}/) ([DMG](https://github.com/attilameget/HomeWlanTrainer/raw/cursor/add-kickr-spec/dist/{ver}/steadyGrind-{ver}-macos.dmg)).

Rebuild locally (output goes to `dist/<version>/`; runs unit + e2e tests first):

```bash
./deploy/macos/build_dmg.sh
```
"""
readme2, n = re.subn(
    r"## Share with a friend \(macOS DMG installer\).*?(?=\n## |\n\*\*On your friend's Mac\*\*)",
    block + "\n",
    readme,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit(f"README Share section replace failed (n={n})")
Path("README.md").write_text(readme2)

dist_readme = Path("dist/README.md").read_text()
# Replace the v1.0.0 (or current) latest section header body until next ## macOS
latest = f"""## macOS — v{ver} (latest)

What's new: [`WHAT_IS_NEW.md`]({ver}/WHAT_IS_NEW.md) · full log: [`CHANGELOG.md`](../CHANGELOG.md)

| File | Path |
| --- | --- |
| Installer | [`dist/{ver}/steadyGrind-{ver}-macos.dmg`]({ver}/steadyGrind-{ver}-macos.dmg) |
| Version stamp | [`dist/{ver}/VERSION`]({ver}/VERSION) |
| GitHub Release | [v{ver}](https://github.com/attilameget/HomeWlanTrainer/releases/tag/v{ver}) |

```bash
curl -fL -o steadyGrind-{ver}-macos.dmg \\
  https://github.com/attilameget/HomeWlanTrainer/releases/download/v{ver}/steadyGrind-{ver}-macos.dmg

# or from the repo tree:
curl -fL -o steadyGrind-{ver}-macos.dmg \\
  https://github.com/attilameget/HomeWlanTrainer/raw/cursor/add-kickr-spec/dist/{ver}/steadyGrind-{ver}-macos.dmg
```

"""
dist2, n = re.subn(
    rf"## macOS — v{re.escape(ver)} \(latest\).*?(?=\n## macOS —)",
    latest,
    dist_readme,
    count=1,
    flags=re.S,
)
if n != 1:
    # insert at top after intro
    parts = dist_readme.split("\n## macOS —", 1)
    if len(parts) != 2:
        raise SystemExit("dist/README structure unexpected")
    dist2 = parts[0] + latest + "\n## macOS —" + parts[1]
Path("dist/README.md").write_text(dist2)
print(f"updated docs for {ver}")
PY

git add "dist/${VERSION}/" README.md dist/README.md
if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi

git commit -m "Add steadyGrind ${VERSION} macOS DMG installer."
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git push -u origin "${BRANCH}"
ls -lh "${DMG}"
echo "==> Published ${DMG} on ${BRANCH}"
