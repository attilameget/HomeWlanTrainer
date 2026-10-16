"""Windows bootstrap helpers (no GUI MessageBox required)."""

from __future__ import annotations

from pathlib import Path

from steadygrind.windows_bootstrap import agent_log_path, configure_agent_logging, report_fatal


def test_configure_agent_logging_writes_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "steadygrind.windows_bootstrap.agent_log_dir", lambda: tmp_path
    )
    path = configure_agent_logging()
    assert path == tmp_path / "agent.log"
    import logging

    logging.getLogger("steadygrind.test").info("hello")
    assert "hello" in path.read_text(encoding="utf-8")


def test_report_fatal_appends_traceback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "steadygrind.windows_bootstrap.agent_log_dir", lambda: tmp_path
    )
    monkeypatch.setattr(
        "steadygrind.windows_bootstrap.show_error_dialog", lambda *_a, **_k: None
    )
    path = report_fatal("unit-test", RuntimeError("boom"))
    text = path.read_text(encoding="utf-8")
    assert "boom" in text
    assert "RuntimeError" in text
    assert path == agent_log_path() or path == tmp_path / "agent.log"
