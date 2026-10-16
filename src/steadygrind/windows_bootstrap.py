"""Early Windows diagnostics for the frozen tray app (log + MessageBox)."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path


def agent_log_dir() -> Path:
    try:
        from platformdirs import user_log_dir

        path = Path(user_log_dir("steadyGrind", "steadyGrind"))
    except Exception:
        path = Path.home() / "AppData" / "Local" / "steadyGrind" / "Logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def agent_log_path() -> Path:
    return agent_log_dir() / "agent.log"


def configure_agent_logging() -> Path:
    """Write agent logs to disk so a windowless exe still leaves a trail."""
    path = agent_log_path()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers when re-entered.
    marker = "steadygrind-agent-file"
    if not any(getattr(h, "steadygrind_marker", None) == marker for h in root.handlers):
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler.steadygrind_marker = marker  # type: ignore[attr-defined]
        root.addHandler(handler)
    # Also keep stderr if a console is attached (debug .cmd / console builds).
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(stream)
    return path


def show_error_dialog(title: str, message: str) -> None:
    """Native MessageBox so a windowless crash is still visible."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def report_fatal(where: str, exc: BaseException) -> Path:
    """Log a full traceback and show a short MessageBox. Returns the log path."""
    path = configure_agent_logging()
    logging.getLogger(__name__).exception("fatal error in %s", where)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- fatal in {where} ---\n{tb}\n")
    except OSError:
        pass
    show_error_dialog(
        "steadyGrind failed to start",
        f"{type(exc).__name__}: {exc}\n\nDetails were written to:\n{path}",
    )
    return path
