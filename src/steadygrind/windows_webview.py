"""Windows steadyGrind window: Edge WebView2 via pywebview, no browser chrome.

The tray agent owns this window. The ride engine stays in the server process.
"""

from __future__ import annotations

import logging
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from steadygrind.macos_webview import (
    is_local_ui_url,
    should_download_response,
    unique_download_path,
)

logger = logging.getLogger(__name__)

_window: Any = None
_window_lock = threading.Lock()
_loop_started = False


def webview_available() -> bool:
    """True when pywebview can host the UI (Edge WebView2 on Windows 11)."""
    if sys.platform != "win32":
        return False
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True


def startup_splash_wanted(
    *, open_ui: bool, frozen: bool, port_open: bool
) -> bool:
    """Splash only when we will open the UI and the server is not already up."""
    del frozen  # reserved for parity with the macOS helper
    return bool(open_ui and not port_open)


def show_startup_splash() -> None:
    """No separate splash on Windows; the tray title shows Starting…"""
    return None


def hide_startup_splash() -> None:
    return None


def _downloads_dir() -> Path:
    path = Path.home() / "Downloads"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path.home()
    return path


def present_ui(url: str, *, port: int = 8080) -> bool:
    """Show or focus the steadyGrind WebView2 window. Returns False on failure."""
    if not webview_available():
        return False
    import webview

    global _window, _loop_started

    with _window_lock:
        if _window is not None:
            try:
                _window.show()
                _window.restore()
                return True
            except Exception:  # noqa: BLE001
                _window = None

        def _on_navigation(_window_obj: Any, uri: str) -> bool | None:
            if is_local_ui_url(uri, port=port):
                return None
            webbrowser.open(uri)
            return False

        window = webview.create_window(
            "steadyGrind",
            url,
            width=1280,
            height=800,
            min_size=(360, 640),
            background_color="#121417",
        )
        try:
            window.events.navigating += _on_navigation
        except Exception:  # noqa: BLE001
            logger.debug("webview navigating hook unavailable", exc_info=True)
        window.events.closing += _on_closing
        _window = window

        if not _loop_started:
            _loop_started = True
            threading.Thread(
                target=lambda: webview.start(gui="edgechromium", debug=False),
                daemon=True,
                name="steadygrind-webview",
            ).start()
        return True


def _on_closing() -> None:
    """Closing the window leaves the tray agent running."""
    global _window
    with _window_lock:
        _window = None


def reload_ui() -> bool:
    with _window_lock:
        window = _window
    if window is None:
        return False
    try:
        current = None
        try:
            current = window.get_current_url()
        except Exception:  # noqa: BLE001
            current = None
        window.load_url(current or "http://127.0.0.1:8080")
        return True
    except Exception:  # noqa: BLE001
        logger.warning("reload_ui failed", exc_info=True)
        return False


def quit_ui() -> None:
    global _window
    with _window_lock:
        window = _window
        _window = None
    if window is None:
        return
    try:
        window.destroy()
    except Exception:  # noqa: BLE001
        pass


def save_download_bytes(filename: str, data: bytes) -> Path:
    """Write a FIT (or other) download under Downloads. Used by tests/helpers."""
    path = unique_download_path(_downloads_dir(), filename)
    path.write_bytes(data)
    return path


def should_keep_download(*, url: str, mime: str, content_disposition: str) -> bool:
    return should_download_response(
        url=url, mime=mime, content_disposition=content_disposition
    )
