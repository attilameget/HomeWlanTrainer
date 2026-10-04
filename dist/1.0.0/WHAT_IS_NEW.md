# What's new in 1.0.0

Released **2026-10-04**. Full project history: [CHANGELOG.md](../../CHANGELOG.md).

## Highlights

- **Plan.** New Plan screen builds an on-host bike+run calendar from FTP, saved rides, and Garmin history. Bike days are ERG-playable; run days are guidance; optional Sync to Garmin.
- **Claude sketches.** With an Anthropic API key on Plan (collapsed settings), generate with Claude (`claude-sonnet-5-5` default); otherwise rules-based. Keys never leave your machine via settings responses.
- **Week ahead.** After a saved ride of 30+ minutes, the next week starting tomorrow can refresh automatically.
- Same-day bike+run doubles so high day counts (e.g. 5 bike + 4 run) are honored.

## Installer

Build the Apple silicon DMG on a Mac (PyInstaller + `hdiutil`):

```bash
git checkout cursor/add-kickr-spec && git pull
./deploy/macos/build_dmg.sh
# → dist/1.0.0/steadyGrind-1.0.0-macos.dmg
```

After the DMG is committed here, publish GitHub Release: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v1.0.0
