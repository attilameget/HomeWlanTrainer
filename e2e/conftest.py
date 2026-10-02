"""E2E fixtures: isolated kickr-pi + Playwright page with Emulator mode."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2.0) as resp:
        return json.loads(resp.read().decode())


def _wait_ready(base: str, *, timeout_s: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            st = _get_json(f"{base}/api/status")
            if st.get("emulator") and st.get("engine", {}).get("trainer_connected"):
                return st
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
        time.sleep(0.25)
    raise RuntimeError(f"app not ready at {base}: {last_err}")


@pytest.fixture(scope="session")
def e2e_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start kickr-pi with Emulator on an ephemeral port and isolated HOME."""
    port = _free_port()
    home = tmp_path_factory.mktemp("kickr-e2e-home")
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "KICKR_HOST": "127.0.0.1",
            "KICKR_PORT": str(port),
            "KICKR_TRAINER_MODE": "simulated",
            "KICKR_ALLOW_SIMULATED": "true",
            "KICKR_AUTO_CONNECT": "false",
            # Keep Real-mode switches snappy in CI/desk e2e (no long mDNS wait)
            "KICKR_DISCOVER_TIMEOUT_S": "2",
            "PATH": os.environ.get("PATH", ""),
        }
    )
    # Prefer project venv kickr-pi via uv
    cmd = ["uv", "run", "kickr-pi"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(base)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture
def page(e2e_base_url: str) -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        pg = context.new_page()
        pg.goto(e2e_base_url, wait_until="domcontentloaded")
        pg.wait_for_selector("#btn-manual-start")
        yield pg
        context.close()
        browser.close()
