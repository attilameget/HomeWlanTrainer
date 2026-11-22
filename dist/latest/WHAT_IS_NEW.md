# What's new in 1.5.2

Released **2026-11-22**. Full project history: [CHANGELOG.md](../../CHANGELOG.md).

## Highlights

- **Finished-ride handoff.** When the host reaches Finished (last-stage Skip, natural finish, or remote stop), the ride screen no longer stays open as a frozen zombie — summary returns you to Home, and ride controls disable while inactive.
- **Reconnect hardening.** Metrics-loop exit or control-point failures during recovery no longer leave the clock stuck in Reconnecting while the trainer link is still up; disconnect wakes blocked metrics waiters.

## Installer

- `steadyGrind-1.5.2-macos.dmg` (this folder)
- `steadyGrind-1.5.2-windows.zip` (this folder)
- GitHub Release: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v1.5.2
