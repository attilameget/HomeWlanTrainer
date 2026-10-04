# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Adaptive multi-sport training plan:** Plan screen generates an on-host bike+run plan from FTP, local saved rides, and Garmin activity history; bike days are ERG-playable; run days are guidance; optional Sync to Garmin (FR-33–35)
- **Local Ollama** plan sketches (default `llama3.1:8b`) with rules fallback; enable/URL/model on the Plan page (FR-33, FR-35)
- **Post-ride week-ahead refresh:** after a saved ride ≥30 min, regenerate the next week starting tomorrow (FR-36)
- **Install-time Ollama:** macOS `run.sh` / Pi `install.sh` run `ensure_ollama.sh`; feature enabled only when Ollama is ready, otherwise left off (FR-37)

### Changed

- Default `ollama_enabled` is **false** until install/run confirms Ollama
- Plan UI is isolated behind the **Plan** button; Home only gains plan bike rows in **Library** (Source: Plan). No Home proposal strip; Today stays Garmin-only; Ollama controls live on the Plan page (FR-35)

### Fixed

- Garmin login felt stuck after credentials: Settings no longer waits on Home calendar/library refresh; Home loads workouts in one parallelized request; password login skips a stale-token probe before SSO (FR-01)

## [0.3.4] - 2026-10-03

**Saved rides as FIT.** Stop a ride to keep a downloadable FIT file on Home.

Requirements: [specification/SPEC.md](specification/SPEC.md) (FR-19).

### Added

- **Saved rides:** Stop writes a FIT activity (Real KICKR and Emulator); Home lists date, time, length, and average watts with Download and Delete (FR-19)

### Changed

- Home vertical spacing is even between Today/Manual, Library, and Saved rides

## [0.3.3] - 2026-10-03

**macOS heart rate.** Connect a Garmin HRM-Pro or other Bluetooth strap from Settings and see bpm on the ride screen.

Requirements: [specification/SPEC.md](specification/SPEC.md) (FR-20).

### Added

- macOS Settings **Heart rate**: Discover / Connect / Disconnect and Autoconnect for a Garmin HRM-Pro or other Bluetooth strap; the ride screen shows bpm (no chart). Hidden on Raspberry Pi (FR-20)

## [0.3.2] - 2026-10-03

### Added

- README features Emulator UI screenshots (home, preview, ride, settings)

## [0.3.1] - 2026-10-03

**steadyGrind** product rename, ride structure+power overlay, Garmin record help, and Settings during rides.

Requirements: [specification/SPEC.md](specification/SPEC.md) (FR-30–FR-32).

### Added

- Settings **Record session with Garmin** opens a help modal (ANT+ pairing, watch settings, Strava tips) (FR-30)
- Ride **structure + power overlay**: zone profile under adherence power line (−2m…+8m; Manual stays power-only) (FR-31)
- README screenshot capture skill + Emulator UI stills under `docs/screenshots/`

### Changed

- Product name is **steadyGrind** (macOS app, DMG, dialogs, docs). Python package / CLI remain `kickr-pi` for compatibility.

### Fixed

- Opening Settings during a ride no longer snaps back to the ride view on each live tick; Settings back link becomes **Back to ride** while a session is active (FR-32)

## [0.3.0] - 2026-10-02

**steadyGrind** UI theme, ride-flow polish, Autoconnect, and a Playwright e2e harness.

Requirements: [specification/SPEC.md](specification/SPEC.md) (FR-06, FR-18, FR-21–FR-29).

### Added

- **Autoconnect** Settings toggle (persisted): when Real KICKR is offline, rediscover/reconnect ~every 15 s; Disconnect pauses until Connect or Autoconnect is turned on again
- Auto-pause/resume workout clock when the trainer pauses or cadence stops (~3 s); auto-resume when pedaling / trainer restarts (manual Pause still requires Resume)
- In-app stop **Workout summary** dialog: elapsed time, average watts; **Back to workout** / **Back to main screen**
- Start / Start manual disabled when trainer or Emulator is not connected
- Workout preview **power profile chart** (zone-coloured stages, FTP line, tap for duration / target / % FTP / zone)
- Emulator desk API `POST /api/emulator/cadence` to set reported rpm
- **UI E2E harness** under `e2e/` (Playwright + Emulator; not shipped): Manual ERG golden path, trainer chip, connection buttons, timer/cadence, Autoconnect, preview chart
- macOS builds run unit + UI e2e tests before packaging (`deploy/macos/run_pre_dist_tests.sh`)

### Changed

- **UI theme (steadyGrind):** light cool-blue palette, Public Sans, home with Today chart + Manual watt stepper + Library table, connection pills
- Emulator panel only visible on the ride screen when Emulator mode is active
- SPEC stamp 2026-10-02; FR list through FR-29 (Autoconnect, preview chart, e2e)

### Fixed

- Ride timer starts / advances only when cadence is present (no elapsed without pedaling)
- Settings Discover / Connect / Disconnect enablement follows Real KICKR connection state (Discover/Connect disabled in Emulator mode)
- Trainer status chip reflects connected vs off (ok / bad)

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

[Unreleased]: https://github.com/attilameget/HomeWlanTrainer/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.3.4
[0.3.3]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.3.3
[0.3.2]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.3.2
[0.3.1]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.3.1
[0.3.0]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.3.0
[0.2.0]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.2.0
[0.1.0]: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.1.0
