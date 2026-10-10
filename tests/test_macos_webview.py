"""URL and download policy for the macOS WebKit window (no AppKit)."""

from __future__ import annotations

import sys
from pathlib import Path

from kickr_pi.macos_agent import collect_kickr_restart_pids, is_kickr_command
from kickr_pi.macos_webview import (
    is_local_ui_url,
    present_ui,
    safe_download_name,
    should_download_response,
    unique_download_path,
    webkit_available,
    window_is_fullscreen,
)


def test_local_ui_urls_stay_in_the_window() -> None:
    assert is_local_ui_url("http://127.0.0.1:8080/", port=8080)
    assert is_local_ui_url("http://127.0.0.1:8080/api/status?x=1", port=8080)
    assert is_local_ui_url("http://localhost:8080/assets/app.js", port=8080)
    assert is_local_ui_url("http://[::1]:8080/", port=8080)
    assert is_local_ui_url("https://127.0.0.1:8443/ride", port=8443)
    assert is_local_ui_url("/settings", port=8080)
    assert is_local_ui_url("about:blank", port=8080)
    assert is_local_ui_url(None, port=8080)


def test_off_app_urls_leave_the_window() -> None:
    assert not is_local_ui_url("https://console.anthropic.com/", port=8080)
    assert not is_local_ui_url("http://192.168.1.20:8080/", port=8080)
    assert not is_local_ui_url("http://127.0.0.1:9/", port=8080)
    assert not is_local_ui_url("http://127.0.0.1/", port=8080)
    assert not is_local_ui_url("mailto:rider@example.com", port=8080)


def test_fit_and_attachment_responses_download() -> None:
    fit = "http://127.0.0.1:8080/api/rides/abc/fit"
    assert should_download_response(
        url=fit,
        mime="application/octet-stream",
        content_disposition='attachment; filename="ride.fit"',
    )
    assert should_download_response(
        url=fit,
        mime="text/plain",
        content_disposition="",
    )
    assert not should_download_response(
        url="http://127.0.0.1:8080/",
        mime="text/html",
        content_disposition="",
    )
    assert not should_download_response(
        url="http://127.0.0.1:8080/api/status",
        mime="application/json",
        content_disposition="",
    )


def test_download_names_stay_inside_the_folder(tmp_path: Path) -> None:
    assert safe_download_name("../../etc/passwd") == "passwd"
    assert safe_download_name("..") == "download"
    assert safe_download_name(None) == "download"
    first = unique_download_path(tmp_path, "ride.fit")
    first.write_bytes(b"a")
    second = unique_download_path(tmp_path, "ride.fit")
    assert first.name == "ride.fit"
    assert second.name == "ride-2.fit"
    assert second.parent == tmp_path


def test_dev_restart_stops_previous_source_and_packaged_app() -> None:
    assert is_kickr_command("/repo/.venv/bin/python -m kickr_pi")
    assert is_kickr_command("/Applications/steadyGrind.app/Contents/MacOS/steadyGrind")
    assert not is_kickr_command("/usr/bin/nginx")

    source = collect_kickr_restart_pids(
        [(420, "/repo/.venv/bin/python -m kickr_pi", 410, "python -m kickr_pi --macos-agent")],
        own_pid=999,
    )
    assert source == [410, 420]

    packaged = collect_kickr_restart_pids(
        [(
            50,
            "/Applications/steadyGrind.app/Contents/Resources/kickr-pi/kickr-pi --server-only",
            40,
            "/Applications/steadyGrind.app/Contents/MacOS/steadyGrind --macos-agent",
        )],
        own_pid=999,
    )
    assert packaged == [40, 50]

    assert collect_kickr_restart_pids([(80, "/usr/bin/nginx", 1, "launchd")], own_pid=999) == []
    assert collect_kickr_restart_pids(
        [(999, "python -m kickr_pi", 1, "launchd")],
        own_pid=999,
    ) == []


def test_fullscreen_window_is_its_own_desktop() -> None:
    fullscreen = 1 << 14
    titled = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)
    assert window_is_fullscreen(titled | fullscreen)
    assert not window_is_fullscreen(titled)
    assert not window_is_fullscreen(0)


def test_webkit_window_is_unavailable_off_mac() -> None:
    if sys.platform == "darwin":
        return
    assert webkit_available() is False
    assert present_ui("http://127.0.0.1:8080") is False
