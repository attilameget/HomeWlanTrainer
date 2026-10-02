# Distribution downloads

Published installers live under **versioned folders**: `dist/<version>/`.

PyInstaller scratch (`kickr-pi/`, `KICKR Pi.app/`) stays at the top of `dist/` and is gitignored.

## macOS — v0.2.0 (latest)

What's new: [`WHAT_IS_NEW.md`](0.2.0/WHAT_IS_NEW.md) · full log: [`CHANGELOG.md`](../CHANGELOG.md)

| File | Path |
| --- | --- |
| Installer | [`dist/0.2.0/KICKR-Pi-0.2.0-macos.dmg`](0.2.0/KICKR-Pi-0.2.0-macos.dmg) |
| Version stamp | [`dist/0.2.0/VERSION`](0.2.0/VERSION) |
| GitHub Release | [v0.2.0](https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.2.0) |

```bash
curl -fL -o KICKR-Pi-0.2.0-macos.dmg \
  https://github.com/attilameget/HomeWlanTrainer/releases/download/v0.2.0/KICKR-Pi-0.2.0-macos.dmg

# or from the repo tree:
curl -fL -o KICKR-Pi-0.2.0-macos.dmg \
  https://github.com/attilameget/HomeWlanTrainer/raw/cursor/add-kickr-spec/dist/0.2.0/KICKR-Pi-0.2.0-macos.dmg
```

## macOS — v0.1.0

What's new: [`WHAT_IS_NEW.md`](0.1.0/WHAT_IS_NEW.md)

| File | Path |
| --- | --- |
| Installer | [`dist/0.1.0/KICKR-Pi-0.1.0-macos.dmg`](0.1.0/KICKR-Pi-0.1.0-macos.dmg) |
| GitHub Release | [v0.1.0](https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.1.0) |

Rebuild locally (reads version from `pyproject.toml`):

```bash
./deploy/macos/build_dmg.sh
# → dist/<version>/KICKR-Pi-<version>-macos.dmg
```

## Raspberry Pi

No DMG — install from source on the Pi (see [deploy/raspberrypi/README.md](../deploy/raspberrypi/README.md)).
