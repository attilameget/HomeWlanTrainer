"""Unit tests for macOS LaunchAgent helpers (no GUI)."""

from __future__ import annotations

import plistlib
from pathlib import Path

from steadygrind.macos_launchagent import (
    LAUNCH_AGENT_LABEL,
    build_launch_agent_plist,
    launch_agent_installed,
    launch_agent_plist_path,
    remove_launch_agent_plist,
    resolve_bundle_launcher,
    write_launch_agent_plist,
)


def test_build_launch_agent_plist_points_at_executable() -> None:
    exe = Path("/Applications/steadyGrind.app/Contents/MacOS/steadyGrind")
    plist = build_launch_agent_plist(exe)
    assert plist["Label"] == LAUNCH_AGENT_LABEL
    assert plist["ProgramArguments"] == [str(exe), "--no-browser"]
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True


def test_write_and_remove_launch_agent_plist(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    exe = Path("/Applications/steadyGrind.app/Contents/MacOS/steadyGrind")
    path = write_launch_agent_plist(exe, home=home)
    assert path == launch_agent_plist_path(home)
    assert path.is_file()
    assert launch_agent_installed(home=home)
    with path.open("rb") as fh:
        data = plistlib.load(fh)
    assert data["Label"] == LAUNCH_AGENT_LABEL
    assert remove_launch_agent_plist(home=home) is True
    assert not launch_agent_installed(home=home)


def test_resolve_bundle_launcher_from_frozen_layout(tmp_path: Path) -> None:
    contents = tmp_path / "steadyGrind.app" / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources" / "steadygrind"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    launcher = macos / "steadyGrind"
    launcher.write_text("#!/bin/bash\n")
    launcher.chmod(0o755)
    binary = resources / "steadygrind"
    binary.write_text("x")
    binary.chmod(0o755)
    assert resolve_bundle_launcher(binary) == launcher.resolve()
