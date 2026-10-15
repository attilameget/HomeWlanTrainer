"""Unit tests for Windows Open at Login helpers (no GUI)."""

from __future__ import annotations

from pathlib import Path

from steadygrind.windows_startup import (
    STARTUP_FILENAME,
    build_dev_startup_script,
    build_startup_script,
    disable_open_at_login,
    enable_open_at_login,
    resolve_windows_launcher,
    startup_installed,
    startup_script_path,
    write_startup_script,
)


def test_build_startup_script_points_at_executable() -> None:
    exe = Path(r"C:\Apps\steadyGrind\steadyGrind.exe")
    body = build_startup_script(exe)
    assert "--windows-agent" in body
    assert "--no-browser" in body
    assert "steadyGrind.exe" in body


def test_build_dev_startup_script_uses_module_form() -> None:
    body = build_dev_startup_script(Path(r"C:\Python\python.exe"))
    assert "python.exe" in body
    assert "-m steadygrind" in body
    assert "--windows-agent" in body
    assert "--no-browser" in body


def test_write_and_remove_startup_script(tmp_path: Path) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    exe = Path(r"C:\Apps\steadyGrind\steadyGrind.exe")
    path = write_startup_script(exe, appdata=appdata)
    assert path == startup_script_path(appdata=appdata)
    assert path.name == STARTUP_FILENAME
    assert path.is_file()
    assert startup_installed(appdata=appdata)
    text = path.read_text(encoding="utf-8")
    assert "--windows-agent" in text
    disable_open_at_login(appdata=appdata)
    assert not startup_installed(appdata=appdata)


def test_enable_open_at_login(tmp_path: Path) -> None:
    appdata = tmp_path / "Roaming"
    exe = Path("/tmp/steadyGrind.exe")
    path = enable_open_at_login(exe, appdata=appdata)
    assert path.is_file()


def test_resolve_windows_launcher_from_frozen_name(tmp_path: Path) -> None:
    exe = tmp_path / "steadyGrind.exe"
    exe.write_text("x", encoding="utf-8")
    assert resolve_windows_launcher(exe) == exe.resolve()
