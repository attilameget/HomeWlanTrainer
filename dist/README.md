# Distribution downloads

Built installers are published as **GitHub Release** assets (not stored as git blobs).

## macOS

| File | Release |
| --- | --- |
| `KICKR-Pi-0.1.0-macos.dmg` | [v0.1.0](https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.1.0) |

Download:

```bash
curl -fL -o KICKR-Pi-0.1.0-macos.dmg \
  https://github.com/attilameget/HomeWlanTrainer/releases/download/v0.1.0/KICKR-Pi-0.1.0-macos.dmg
```

Rebuild locally: `./deploy/macos/build_dmg.sh` → `dist/KICKR-Pi-<version>-macos.dmg`

## Raspberry Pi

There is no DMG for Linux — install from source on the Pi:

```bash
curl -fsSL https://github.com/attilameget/HomeWlanTrainer/archive/refs/heads/cursor/add-kickr-spec.tar.gz \
  | tar -xz
cd HomeWlanTrainer-cursor-add-kickr-spec
sudo ./deploy/raspberrypi/install.sh
```

See [deploy/raspberrypi/README.md](../deploy/raspberrypi/README.md).
