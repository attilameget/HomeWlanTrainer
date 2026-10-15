"""Windows tray agent: keep the server running, Open UI, Open at Login, Quit."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from steadygrind.windows_startup import (
    disable_open_at_login,
    enable_open_at_login,
    resolve_windows_launcher,
    startup_installed,
)

logger = logging.getLogger(__name__)

UI_URL = "http://127.0.0.1:8080"
STATUS_URL = f"{UI_URL}/api/status"
PREFS_NAME = "agent.json"


def _prefs_path() -> Path:
    from platformdirs import user_data_dir

    base = Path(user_data_dir("steadyGrind", "steadyGrind"))
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


def is_kickr_command(command: str) -> bool:
    lowered = command.lower()
    return "steadygrind" in lowered or "kickr_pi" in lowered or "kickr-pi" in lowered


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


def _listen_pids_windows(port: int) -> list[int]:
    """Return PIDs listening on TCP ``port`` (Windows netstat)."""
    try:
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return []
    needle = f":{port}"
    pids: list[int] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        if "LISTENING" not in parts and "LISTEN" not in parts:
            continue
        local = parts[1] if len(parts) > 1 else ""
        if not local.endswith(needle):
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def _taskkill(pids: list[int]) -> None:
    for pid in pids:
        if pid <= 1 or pid == os.getpid():
            continue
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue


def _wait_port_free(port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not port_listening(port):
            return True
        time.sleep(0.1)
    return not port_listening(port)


def replace_running_kickr(port: int = 8080) -> None:
    """Stop a steadyGrind already bound to ``port`` so this source launch can serve it."""
    if not port_listening(port):
        return
    pids = _listen_pids_windows(port)
    if not pids:
        return
    logger.info("Stopping steadyGrind on port %s so this launch loads the current UI", port)
    _taskkill(pids)
    _wait_port_free(port, 4.0)


def server_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--server-only"]
    return [sys.executable, "-m", "steadygrind"]


def open_url(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def copy_clipboard(text: str) -> None:
    """Copy text to the Windows clipboard (best-effort)."""
    try:
        import ctypes

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard(0)
        user32.EmptyClipboard()
        encoded = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, encoded, len(encoded))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        user32.CloseClipboard()
    except Exception:  # noqa: BLE001
        try:
            subprocess.run(
                ["clip"],
                input=text.encode("utf-16-le"),
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            logger.warning("could not copy phone URL to clipboard")


def present_local_ui() -> None:
    """Open the steadyGrind window, or the default browser if WebView2 is missing."""
    from steadygrind.windows_webview import present_ui, webview_available

    if webview_available() and present_ui(UI_URL):
        return
    open_url(UI_URL)


def _tray_image():
    """Small tray icon (Pillow). Falls back to a generated green square."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 5, size - 5), fill=(46, 160, 67, 255))
    draw.ellipse((20, 20, size - 21, size - 21), fill=(18, 20, 23, 255))
    return img


class WindowsAgent:
    def __init__(self, *, open_browser: bool = True) -> None:
        self.open_browser = open_browser
        self._server: subprocess.Popen[bytes] | None = None
        self._owns_server = False
        self._status = "Starting…"
        self._icon = None
        self._prefs = load_prefs()
        self._quitting = False
        self._login_enabled = False

    def _log_dir(self) -> Path:
        from platformdirs import user_log_dir

        path = Path(user_log_dir("steadyGrind", "steadyGrind"))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _launcher_path(self) -> Path | None:
        return resolve_windows_launcher(Path(sys.argv[0]).resolve())

    def start_server(self) -> None:
        if not getattr(sys, "frozen", False):
            replace_running_kickr(8080)
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
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._server = subprocess.Popen(
            server_command(),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=creationflags,
        )
        self._owns_server = True
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
            return bool(self._prefs["open_at_login"]) and startup_installed()
        return startup_installed()

    def set_login_enabled(self, enabled: bool) -> None:
        launcher = self._launcher_path()
        if enabled:
            if launcher is None:
                # Dev launches: point Startup at the current interpreter + -m.
                launcher = Path(sys.executable)
                enable_open_at_login(launcher)
                # Overwrite with a richer command for source trees.
                from steadygrind.windows_startup import startup_script_path

                script = startup_script_path()
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text(
                    "@echo off\r\n"
                    f'"{sys.executable}" -m steadygrind --windows-agent --no-browser\r\n',
                    encoding="utf-8",
                    newline="\r\n",
                )
            else:
                enable_open_at_login(launcher)
            self._prefs["open_at_login"] = True
        else:
            disable_open_at_login()
            self._prefs["open_at_login"] = False
        self._prefs["login_prompted"] = True
        save_prefs(self._prefs)
        self._login_enabled = enabled
        self._refresh_menu()

    def quit_app(self, icon=None, _item=None) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.stop_server()
        from steadygrind.windows_webview import quit_ui

        quit_ui()
        if icon is None:
            icon = self._icon
        if icon is not None:
            icon.stop()

    def _title(self) -> str:
        return {
            "Running": "● SG",
            "Starting…": "○ SG",
            "Error": "✖ SG",
        }.get(self._status, "SG")

    def _refresh_menu(self) -> None:
        icon = self._icon
        if icon is None:
            return
        icon.title = f"steadyGrind — {self._status}"
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def _build_menu(self):
        import pystray

        agent = self

        def open_ui(icon, item) -> None:  # noqa: ARG001
            present_local_ui()

        def copy_url(icon, item) -> None:  # noqa: ARG001
            ip = _lan_ipv4()
            url = f"http://{ip}:8080" if ip else UI_URL
            copy_clipboard(url)

        def toggle_login(icon, item) -> None:  # noqa: ARG001
            agent.set_login_enabled(not agent.login_enabled())

        def quit_item(icon, item) -> None:
            agent.quit_app(icon, item)

        return pystray.Menu(
            pystray.MenuItem("Open UI", open_ui, default=True),
            pystray.MenuItem("Copy phone URL", copy_url),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Open at Login",
                toggle_login,
                checked=lambda _item: agent.login_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_item),
        )

    def run(self) -> None:
        try:
            import pystray
        except ImportError as exc:
            raise SystemExit(
                "Windows agent needs pystray (install steadygrind[ble] on Windows)"
            ) from exc

        self._login_enabled = self.login_enabled()
        icon = pystray.Icon(
            "steadyGrind",
            _tray_image(),
            f"steadyGrind — {self._status}",
            menu=self._build_menu(),
        )
        self._icon = icon

        def boot() -> None:
            agent = self
            agent.ensure_default_login_item()
            agent.start_server()
            if agent.open_browser and agent._status == "Running":
                present_local_ui()
                agent._prefs["opened_browser_once"] = True
                save_prefs(agent._prefs)
            while not agent._quitting:
                if port_listening(8080):
                    agent._status = "Running"
                elif agent._server is not None and agent._server.poll() is not None:
                    agent._status = "Error"
                agent._refresh_menu()
                time.sleep(2.0)

        threading.Thread(target=boot, daemon=True, name="steadygrind-boot").start()
        icon.run()


def run_windows_agent(*, open_browser: bool = True) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    WindowsAgent(open_browser=open_browser).run()
