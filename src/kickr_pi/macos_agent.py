"""macOS menu-bar agent: keep the server running, Open UI, Open at Login, Quit."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from kickr_pi.macos_launchagent import (
    disable_open_at_login,
    enable_open_at_login,
    launch_agent_installed,
    resolve_bundle_launcher,
)

logger = logging.getLogger(__name__)

UI_URL = "http://127.0.0.1:8080"
STATUS_URL = f"{UI_URL}/api/status"
PREFS_NAME = "agent.json"


def _prefs_path() -> Path:
    base = Path.home() / "Library" / "Application Support" / "steadyGrind"
    base.mkdir(parents=True, exist_ok=True)
    return base / PREFS_NAME


def load_prefs() -> dict:
    path = _prefs_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_prefs(data: dict) -> None:
    path = _prefs_path()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _lan_ipv4() -> str | None:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            addr = probe.getsockname()[0]
            if not addr.startswith("127."):
                return addr
        finally:
            probe.close()
    except OSError:
        return None
    return None


def port_listening(port: int = 8080) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        try:
            sock.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def api_ready(timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    return False


def server_command() -> list[str]:
    if getattr(sys, "frozen", False):
        # Pass an explicit role so PyInstaller bootloader argv reuse cannot
        # re-enter --macos-agent when we spawn ourselves.
        return [sys.executable, "--server-only"]
    return [sys.executable, "-m", "kickr_pi"]


def open_url(url: str) -> None:
    subprocess.run(["open", url], check=False)


def present_local_ui() -> None:
    """Open the steadyGrind window, or the default browser if WebKit is missing."""
    from kickr_pi.macos_webview import present_ui

    if not present_ui(UI_URL):
        open_url(UI_URL)


def copy_pasteboard(text: str) -> None:
    proc = subprocess.run(["pbcopy"], input=text.encode(), check=False)
    _ = proc


class MacosAgent:
    def __init__(self, *, open_browser: bool = True) -> None:
        self.open_browser = open_browser
        self._server: subprocess.Popen[bytes] | None = None
        self._owns_server = False
        self._status = "Starting…"
        self._app = None
        self._status_item = None
        self._login_item = None
        self._prefs = load_prefs()
        self._quitting = False

    def _log_dir(self) -> Path:
        path = Path.home() / "Library" / "Logs" / "steadyGrind"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _launcher_path(self) -> Path | None:
        return resolve_bundle_launcher(Path(sys.argv[0]).resolve())

    def start_server(self) -> None:
        if port_listening(8080):
            self._status = "Running"
            self._owns_server = False
            return
        log_path = self._log_dir() / "server.log"
        log_fh = open(log_path, "ab")  # noqa: SIM115
        env = os.environ.copy()
        env.setdefault("KICKR_HOST", "0.0.0.0")
        env.setdefault("KICKR_PORT", "8080")
        env.setdefault("KICKR_TRAINER_MODE", env.get("KICKR_TRAINER_MODE", "dircon"))
        env["KICKR_ROLE"] = "server"
        self._server = subprocess.Popen(
            server_command(),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=False,
        )
        self._owns_server = True
        # Trainer mDNS discover blocks FastAPI lifespan (and bind) for a while.
        if api_ready(90.0):
            self._status = "Running"
        elif self._server.poll() is not None:
            self._status = "Error"
            logger.error("server exited early; see %s", log_path)
        else:
            self._status = "Error"
            logger.error("server did not become ready; see %s", log_path)

    def stop_server(self) -> None:
        if not self._owns_server or self._server is None:
            return
        if self._server.poll() is None:
            self._server.terminate()
            try:
                self._server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._server.kill()
                self._server.wait(timeout=5)
        self._server = None

    def ensure_default_login_item(self) -> None:
        """First successful .app start: enable Open at Login by default."""
        if self._prefs.get("login_prompted"):
            return
        launcher = self._launcher_path()
        self._prefs["login_prompted"] = True
        if launcher is not None:
            try:
                enable_open_at_login(launcher)
                self._prefs["open_at_login"] = True
            except OSError as exc:
                logger.warning("could not enable Open at Login: %s", exc)
                self._prefs["open_at_login"] = False
        else:
            self._prefs["open_at_login"] = False
        save_prefs(self._prefs)

    def login_enabled(self) -> bool:
        if "open_at_login" in self._prefs:
            return bool(self._prefs["open_at_login"]) and launch_agent_installed()
        return launch_agent_installed()

    def set_login_enabled(self, enabled: bool) -> None:
        launcher = self._launcher_path()
        if enabled:
            if launcher is None:
                self._status = "Error"
                return
            enable_open_at_login(launcher)
            self._prefs["open_at_login"] = True
        else:
            disable_open_at_login()
            self._prefs["open_at_login"] = False
        self._prefs["login_prompted"] = True
        save_prefs(self._prefs)
        if self._login_item is not None:
            self._login_item.setState_(1 if enabled else 0)

    def quit_app(self) -> None:
        """Stop the server and leave the menu-bar run loop. Dock Quit uses this too."""
        if self._quitting:
            return
        self._quitting = True
        from PyObjCTools import AppHelper  # type: ignore[import-untyped]

        from kickr_pi.macos_launchagent import unload_launch_agent

        unload_launch_agent()
        self.stop_server()
        AppHelper.stopEventLoop()

    def run(self) -> None:
        try:
            from AppKit import (  # type: ignore[import-untyped]
                NSApplication,
                NSApplicationActivationPolicyAccessory,
                NSMenu,
                NSMenuItem,
                NSStatusBar,
                NSVariableStatusItemLength,
            )
            from Foundation import NSObject, NSTimer  # type: ignore[import-untyped]
            from PyObjCTools import AppHelper  # type: ignore[import-untyped]
        except ImportError as exc:
            raise SystemExit(
                "macOS agent needs PyObjC AppKit (install kickr-pi[ble] on Mac)"
            ) from exc

        agent = self

        class Delegate(NSObject):
            def openUI_(self, _sender) -> None:  # noqa: N802
                present_local_ui()

            def reloadUI_(self, _sender) -> None:  # noqa: N802
                from kickr_pi.macos_webview import reload_ui

                if not reload_ui():
                    present_local_ui()

            def applicationShouldHandleReopen_hasVisibleWindows_(  # noqa: N802
                self, _app, visible
            ) -> bool:
                if not visible:
                    present_local_ui()
                return True

            def applicationShouldTerminate_(self, _sender) -> int:  # noqa: N802
                agent.quit_app()
                # NSTerminateNow — server is already stopped; Dock Quit must exit.
                return 1

            def copyPhoneURL_(self, _sender) -> None:  # noqa: N802
                ip = _lan_ipv4()
                url = f"http://{ip}:8080" if ip else UI_URL
                copy_pasteboard(url)

            def toggleLogin_(self, sender) -> None:  # noqa: N802
                agent.set_login_enabled(sender.state() != 1)

            def quit_(self, _sender) -> None:  # noqa: N802
                # Unload so KeepAlive does not immediately restart; leave the
                # plist so Open at Login still applies on the next login.
                agent.quit_app()

            def refreshStatus_(self, _timer) -> None:  # noqa: N802
                if port_listening(8080):
                    agent._status = "Running"
                elif agent._server is not None and agent._server.poll() is not None:
                    agent._status = "Error"
                title = {
                    "Running": "● SG",
                    "Starting…": "○ SG",
                    "Error": "✖ SG",
                }.get(agent._status, "SG")
                if agent._status_item is not None:
                    agent._status_item.setTitle_(title)
                    agent._status_item.setToolTip_(f"steadyGrind — {agent._status}")

        def boot() -> None:
            # Install Open at Login immediately so a slow trainer discover cannot
            # skip it if the user quits early.
            agent.ensure_default_login_item()
            agent.start_server()
            if agent.open_browser and agent._status == "Running":
                present_local_ui()
                agent._prefs["opened_browser_once"] = True
                save_prefs(agent._prefs)

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        delegate = Delegate.alloc().init()
        app.setDelegate_(delegate)
        from kickr_pi.macos_webview import install_app_menus, webkit_available

        if webkit_available():
            install_app_menus(delegate)

        status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        status_item.setTitle_("○ SG")
        status_item.setToolTip_("steadyGrind — Starting…")
        self._status_item = status_item

        menu = NSMenu.alloc().init()
        open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open UI", "openUI:", ""
        )
        open_item.setTarget_(delegate)
        menu.addItem_(open_item)

        copy_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Copy phone URL", "copyPhoneURL:", ""
        )
        copy_item.setTarget_(delegate)
        menu.addItem_(copy_item)

        menu.addItem_(NSMenuItem.separatorItem())

        login_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open at Login", "toggleLogin:", ""
        )
        login_item.setTarget_(delegate)
        login_item.setState_(1 if self.login_enabled() else 0)
        menu.addItem_(login_item)
        self._login_item = login_item

        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quit:", "q"
        )
        quit_item.setTarget_(delegate)
        menu.addItem_(quit_item)

        status_item.setMenu_(menu)

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, delegate, "refreshStatus:", None, True
        )

        self._app = app
        threading.Thread(target=boot, daemon=True).start()
        AppHelper.runEventLoop()


def run_macos_agent(*, open_browser: bool = True) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    MacosAgent(open_browser=open_browser).run()
