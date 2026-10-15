"""Open at Login helpers for the Windows tray agent (pure, unit-testable)."""

from __future__ import annotations

import os
from pathlib import Path

STARTUP_FILENAME = "steadyGrind.cmd"
STARTUP_LABEL = "steadyGrind"


def startup_dir(home: Path | None = None, appdata: Path | None = None) -> Path:
    """User Startup folder (runs at interactive logon)."""
    if appdata is not None:
        return (
            appdata
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
    env = os.environ.get("APPDATA")
    if env:
        return (
            Path(env)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
    root = home if home is not None else Path.home()
    return (
        root
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def startup_script_path(
    home: Path | None = None, appdata: Path | None = None
) -> Path:
    return startup_dir(home=home, appdata=appdata) / STARTUP_FILENAME


def build_startup_script(executable: Path) -> str:
    """CMD body that starts the tray agent without opening the UI window."""
    exe = str(executable)
    # Quote the path; forward --no-browser so login starts stay in the tray.
    return (
        "@echo off\r\n"
        f'start "" "{exe}" --windows-agent --no-browser\r\n'
    )


def build_dev_startup_script(python_exe: Path) -> str:
    """CMD body for source-tree launches (`python -m steadygrind …`)."""
    return (
        "@echo off\r\n"
        f'"{python_exe}" -m steadygrind --windows-agent --no-browser\r\n'
    )


def write_startup_script(
    executable: Path,
    home: Path | None = None,
    appdata: Path | None = None,
) -> Path:
    path = startup_script_path(home=home, appdata=appdata)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_startup_script(executable), encoding="utf-8", newline="\r\n")
    return path


def remove_startup_script(
    home: Path | None = None, appdata: Path | None = None
) -> bool:
    path = startup_script_path(home=home, appdata=appdata)
    if path.is_file():
        path.unlink()
        return True
    return False


def startup_installed(
    home: Path | None = None, appdata: Path | None = None
) -> bool:
    return startup_script_path(home=home, appdata=appdata).is_file()


def enable_open_at_login(
    executable: Path,
    home: Path | None = None,
    appdata: Path | None = None,
) -> Path:
    return write_startup_script(executable, home=home, appdata=appdata)


def disable_open_at_login(
    home: Path | None = None, appdata: Path | None = None
) -> None:
    remove_startup_script(home=home, appdata=appdata)


def resolve_windows_launcher(argv0: Path | None = None) -> Path | None:
    """Return the packaged steadyGrind.exe when running from a Windows build."""
    import sys

    candidates: list[Path] = []
    if argv0 is not None:
        candidates.append(argv0)
    candidates.append(Path(sys.argv[0]).resolve())
    if getattr(sys, "frozen", False) and getattr(sys, "executable", None):
        candidates.append(Path(sys.executable).resolve())

    for exe in candidates:
        try:
            exe = exe.resolve()
        except OSError:
            continue
        name = exe.name.lower()
        if name in {"steadygrind.exe", "steadygrind"}:
            return exe
    return None
