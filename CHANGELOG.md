# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-02

Desk **Trainer Emulator** for development without a physical KICKR, plus ride UI polish.

### Added

- **Trainer Emulator (dev):** Settings Real KICKR ↔ Emulator hot-swap while idle; works even when the bike is offline
- Emulator ride panel (side-by-side on laptop): sticky Set watts, Pause/Resume, Follow workout, short presets (`quick_stages`, `ramp_up_down`)
- Emulator-only API (`/api/emulator/*`) gated to `SimulatedTrainer`; 404 when DirCon is active
- Unit/API tests for ramp, pause, desk hold, presets, and DirCon gating

### Changed

- Power history chart uses an adherence-colored **line** (with fill) instead of bars
- Simulated trainer always connects at startup when Emulator mode is selected
- DirCon connect during mode switch is timed so offline bikes do not block Emulator ↔ Real switches

### Notes

- Emulator is a Settings “dev” panel — leave mode on Real KICKR for normal riding
- Desk Set watts holds until you change it, run a preset, or press Follow workout

## [0.1.0] - 2026-09-30

First public release of **KICKR Pi Trainer** — run Garmin Connect cycling workouts on a Wahoo KICKR v6 over Wi‑Fi, with no subscription software.

### Added

- Live Wahoo **Direct Connect** (DirCon) trainer link over Wi‑Fi, with mDNS discovery (`_wahoo-fitness-tnp._tcp`)
- Garmin Connect login (incl. MFA), today’s calendar workout, library browse, and **Garmin Coach** adaptive workouts
- Workout engine: ERG targets, stage timing, pause/resume, skip/previous, ±5 % intensity, manual ERG hold
- Mobile-first web UI: home, preview, ride screen with live power/cadence and pause-aware power chart
- Settings: FTP, Garmin login/logout, trainer discover / connect / **disconnect**
- Screen **Wake Lock** during rides (re-acquires on tab focus / lock release)
- Host sleep guard on macOS (`caffeinate`) while a session is active
- LAN listen on `0.0.0.0:8080` with startup URLs for phone-on-bars use
- **macOS DMG** installer (Apple silicon), published under `dist/<version>/` and as GitHub Release `v0.1.0`
- **Raspberry Pi / Debian 13 (trixie)** install: systemd unit, Avahi / `kickr-pi.local`, update & uninstall scripts

### Changed

- Settings control moved to a compact top-right header button
- Stop ends the session and returns to Home; ride chart pauses the clock while paused

### Notes

- Wake Lock requires a secure context (HTTPS or localhost) on many phones; plain `http://…local` may not keep the screen awake until TLS is added
- Direct Connect is 1:1 — disconnect (or quit) before opening Zwift / the Wahoo app

[Unreleased]: https://github.com/attilameget/HomeWlanTrainer/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.2.0
[0.1.0]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.1.0
