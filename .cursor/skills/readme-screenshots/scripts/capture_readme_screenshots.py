#!/usr/bin/env python3
"""Capture steadyGrind UI screenshots for README / docs.

Starts an isolated Emulator kickr-pi (unless --base-url is given), walks Home →
Preview → Ride → Settings, writes PNGs, then stops the server.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

# .../HomeWlanTrainer/.cursor/skills/readme-screenshots/scripts/this.py → repo root
ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT = ROOT / "docs" / "screenshots"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2.0) as resp:
        return json.loads(resp.read().decode())


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        return json.loads(resp.read().decode())


def _wait_ready(base: str, *, timeout_s: float = 40.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            st = _get_json(f"{base}/api/status")
            if st.get("emulator") and st.get("engine", {}).get("trainer_connected"):
                return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
        time.sleep(0.25)
    raise RuntimeError(f"app not ready at {base}: {last_err}")


def _start_server() -> tuple[subprocess.Popen[str], str, tempfile.TemporaryDirectory[str]]:
    port = _free_port()
    tmp = tempfile.TemporaryDirectory(prefix="steadygrind-shots-")
    home = Path(tmp.name)
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
            "KICKR_DISCOVER_TIMEOUT_S": "2",
            "PATH": os.environ.get("PATH", ""),
        }
    )
    proc = subprocess.Popen(
        ["uv", "run", "kickr-pi"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(base)
    except Exception:
        proc.terminate()
        tmp.cleanup()
        raise
    return proc, base, tmp


def _stop_server(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _shot(page, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=False)
    print(f"wrote {path}")


def capture(base: str, out: Path, *, phone: bool) -> None:
    viewports = [("desktop", 1280, 800, "")]
    if phone:
        viewports.append(("phone", 390, 844, "-phone"))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for _label, width, height, suffix in viewports:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
            )
            page = context.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("#btn-manual-start", timeout=15_000)
            page.wait_for_timeout(400)
            _shot(page, out / f"home{suffix}.png")

            # Preview: built-in demo workout
            page.evaluate(
                """async () => {
                  if (typeof state !== 'undefined') state.workoutId = 'demo';
                }"""
            )
            # Prefer API + UI open via hash-less flow: set workout and click preview API path
            # Load preview through the same REST the UI uses, then navigate by clicking Open
            # after injecting library isn't available — call openPreview via evaluate.
            opened = page.evaluate(
                """async () => {
                  try {
                    if (typeof state !== 'undefined') state.workoutId = 'demo';
                    if (typeof openPreview === 'function') {
                      await openPreview();
                      return true;
                    }
                  } catch (e) {
                    return false;
                  }
                  return false;
                }"""
            )
            if not opened:
                # Fallback: fetch demo and show preview DOM roughly via start not available
                page.goto(f"{base}/", wait_until="domcontentloaded")
            page.wait_for_selector("#view-preview:not(.hidden)", timeout=15_000)
            page.wait_for_selector("#preview-chart", timeout=10_000)
            page.wait_for_timeout(500)
            _shot(page, out / f"preview{suffix}.png")

            # Ride with structure overlay + live-looking power
            _post_json(f"{base}/api/emulator/cadence", {"rpm": 85})
            _post_json(f"{base}/api/session", {"workoutId": "demo"})
            page.evaluate(
                """() => {
                  if (typeof show === 'function') show('ride');
                }"""
            )
            page.wait_for_selector("#view-ride:not(.hidden)", timeout=15_000)
            page.wait_for_selector("#ride-chart", timeout=10_000)
            _post_json(f"{base}/api/emulator/target", {"watts": 150})
            for _ in range(40):
                mode = page.get_attribute("#ride-chart-panel", "data-mode")
                if mode == "overlay":
                    break
                page.wait_for_timeout(250)
            # Let emulator ramp so Actual is non-zero
            page.wait_for_timeout(1800)
            _shot(page, out / f"ride{suffix}.png")

            # Settings
            page.locator('[data-nav="settings"]').first.click()
            page.wait_for_selector("#view-settings:not(.hidden)", timeout=10_000)
            page.wait_for_timeout(400)
            _shot(page, out / f"settings{suffix}.png")

            # Stop session for next viewport
            try:
                _post_json(f"{base}/api/session/command", {"command": "stop"})
            except Exception:
                pass
            context.close()
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Attach to an already-running app instead of starting one",
    )
    parser.add_argument(
        "--phone",
        action="store_true",
        help="Also capture phone viewport (390×844)",
    )
    args = parser.parse_args()

    proc = None
    tmp = None
    base = args.base_url.rstrip("/") if args.base_url else None
    try:
        if base is None:
            print("starting Emulator kickr-pi…")
            proc, base, tmp = _start_server()
            print(f"ready at {base}")
        else:
            print(f"using {base}")
            # Soft wait — may already be Real mode; still try status
            try:
                _wait_ready(base, timeout_s=10.0)
            except RuntimeError as exc:
                print(f"warning: {exc} (continuing anyway)", file=sys.stderr)

        capture(base, args.out.resolve(), phone=args.phone)
        print(f"done → {args.out.resolve()}")
        return 0
    finally:
        if proc is not None:
            _stop_server(proc)
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
