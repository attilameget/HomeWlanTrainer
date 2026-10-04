"""LaunchAgent helpers for the macOS menu-bar agent (pure, unit-testable)."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

LAUNCH_AGENT_LABEL = "com.steadygrind.trainer"
LAUNCH_AGENT_FILENAME = f"{LAUNCH_AGENT_LABEL}.plist"


def launch_agents_dir(home: Path | None = None) -> Path:
    root = home if home is not None else Path.home()
    return root / "Library" / "LaunchAgents"


def launch_agent_plist_path(home: Path | None = None) -> Path:
    return launch_agents_dir(home) / LAUNCH_AGENT_FILENAME


def build_launch_agent_plist(executable: Path) -> dict:
    """Plist body for RunAtLoad + KeepAlive pointing at the .app launcher.

    Extra ``--no-browser`` is forwarded by launcher.sh so login starts do not
    steal focus with Safari.
    """
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(executable), "--no-browser"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(
            Path.home() / "Library" / "Logs" / "steadyGrind" / "agent.stdout.log"
        ),
        "StandardErrorPath": str(
            Path.home() / "Library" / "Logs" / "steadyGrind" / "agent.stderr.log"
        ),
    }


def write_launch_agent_plist(executable: Path, home: Path | None = None) -> Path:
    path = launch_agent_plist_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        plistlib.dump(build_launch_agent_plist(executable), fh, fmt=plistlib.FMT_XML)
    return path


def remove_launch_agent_plist(home: Path | None = None) -> bool:
    path = launch_agent_plist_path(home)
    if path.is_file():
        path.unlink()
        return True
    return False


def launch_agent_installed(home: Path | None = None) -> bool:
    return launch_agent_plist_path(home).is_file()


def _uid() -> str:
    return str(os.getuid())


def load_launch_agent(plist_path: Path) -> None:
    """Load or bootstrap the LaunchAgent (best-effort across macOS versions)."""
    uid = _uid()
    domain = f"gui/{uid}"
    # Prefer modern bootstrap; fall back to load.
    boot = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if boot.returncode == 0:
        return
    # Already loaded → try kickstart; else legacy load
    subprocess.run(
        ["launchctl", "load", "-w", str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def unload_launch_agent(home: Path | None = None) -> None:
    path = launch_agent_plist_path(home)
    uid = _uid()
    domain = f"gui/{uid}/{LAUNCH_AGENT_LABEL}"
    subprocess.run(
        ["launchctl", "bootout", domain],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["launchctl", "unload", "-w", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def enable_open_at_login(
    executable: Path,
    home: Path | None = None,
    *,
    load_now: bool = False,
) -> Path:
    """Install the Open at Login LaunchAgent.

    By default only writes the plist (picked up at next login). Pass
    ``load_now=True`` to bootstrap immediately — avoid that while an agent
    instance is already running, or KeepAlive will start a second copy.
    """
    path = write_launch_agent_plist(executable, home=home)
    if load_now:
        load_launch_agent(path)
    return path


def disable_open_at_login(home: Path | None = None) -> None:
    unload_launch_agent(home=home)
    remove_launch_agent_plist(home=home)


def resolve_bundle_launcher(argv0: Path | None = None) -> Path | None:
    """
    If running inside steadyGrind.app, return Contents/MacOS/steadyGrind.

    Frozen layout: Contents/Resources/kickr-pi/kickr-pi
    """
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
        if exe.name == "kickr-pi" and exe.parent.name == "kickr-pi":
            contents = exe.parent.parent.parent  # …/Resources/kickr-pi/kickr-pi
            launcher = contents / "MacOS" / "steadyGrind"
            if launcher.is_file():
                return launcher
        if exe.name == "steadyGrind" and exe.parent.name == "MacOS":
            return exe

    apps = Path("/Applications/steadyGrind.app/Contents/MacOS/steadyGrind")
    if apps.is_file():
        return apps
    return None
