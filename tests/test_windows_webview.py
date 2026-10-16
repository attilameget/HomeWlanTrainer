"""Pure helpers for the Windows WebView layer (no GUI)."""

from __future__ import annotations

from pathlib import Path

from steadygrind.windows_webview import (
    save_download_bytes,
    should_keep_download,
    startup_splash_wanted,
    webview_available,
)


def test_startup_splash_wanted_only_when_opening_and_port_closed() -> None:
    assert startup_splash_wanted(open_ui=True, frozen=True, port_open=False) is True
    assert startup_splash_wanted(open_ui=True, frozen=True, port_open=True) is False
    assert startup_splash_wanted(open_ui=False, frozen=True, port_open=False) is False


def test_webview_available_false_off_windows() -> None:
    # This CI host is Linux; the helper must not claim WebView2 here.
    assert webview_available() is False


def test_should_keep_download_for_fit() -> None:
    assert should_keep_download(
        url="http://127.0.0.1:8080/api/rides/1/fit",
        mime="application/octet-stream",
        content_disposition="",
    )


def test_save_download_bytes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "steadygrind.windows_webview._downloads_dir", lambda: tmp_path
    )
    path = save_download_bytes("ride.fit", b"FITDATA")
    assert path == tmp_path / "ride.fit"
    assert path.read_bytes() == b"FITDATA"
