"""Heart-rate measurement parsing, monitor freshness, and macOS API gating."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from steadygrind.api import routes as routes_mod
from steadygrind.engine.engine import WorkoutEngine
from steadygrind.hr import create_heart_rate
from steadygrind.hr.autoconnect import HeartRateAutoconnect
from steadygrind.hr.monitor import BleHeartRateMonitor, HeartRateDevice, NullHeartRate
from steadygrind.hr.parse import parse_heart_rate_measurement
from steadygrind.trainer.simulated import SimulatedTrainer


def test_parse_uint8_bpm():
    assert parse_heart_rate_measurement(bytes([0x00, 72])) == 72


def test_parse_uint16_bpm():
    assert parse_heart_rate_measurement(bytes([0x01, 0x48, 0x00])) == 72


def test_parse_ignores_contact_not_detected_and_zero():
    # Flags bits 1–2 == 2: sensor contact supported but not detected.
    assert parse_heart_rate_measurement(bytes([0x04, 80])) is None
    assert parse_heart_rate_measurement(bytes([0x00, 0])) is None
    assert parse_heart_rate_measurement(bytes([0x01])) is None
    assert parse_heart_rate_measurement(b"") is None


def test_parse_contact_detected_still_returns_bpm():
    assert parse_heart_rate_measurement(bytes([0x06, 80])) == 80


def test_stale_reading_clears_bpm():
    now = {"t": 100.0}
    monitor = BleHeartRateMonitor(clock=lambda: now["t"])
    monitor._connected = True  # noqa: SLF001
    monitor.apply_measurement(bytes([0x00, 142]))
    assert monitor.bpm == 142
    now["t"] = 106.0
    assert monitor.bpm is None
    assert monitor.connected is True


def test_create_heart_rate_follows_platform():
    link = create_heart_rate()
    if platform.system() == "Darwin":
        assert link.supported is True
        assert isinstance(link, BleHeartRateMonitor)
    else:
        assert link.supported is False
        assert isinstance(link, NullHeartRate)


class _Hr(NullHeartRate):
    supported = True

    def __init__(self) -> None:
        self._connected = False
        self._device_id: str | None = None
        self._device_name: str | None = None
        self._bpm: int | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def bpm(self) -> int | None:
        return self._bpm

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def device_name(self) -> str | None:
        return self._device_name

    async def discover(self, timeout_s: float = 8.0) -> list[HeartRateDevice]:
        return [HeartRateDevice("uuid-hrm", "HRM-Pro")]

    async def connect(self, device_id: str, name: str | None = None) -> None:
        self._connected = True
        self._device_id = device_id
        self._device_name = name or "HRM-Pro"
        self._bpm = 131

    async def disconnect(self) -> None:
        self._connected = False
        self._bpm = None


@pytest.mark.asyncio
async def test_engine_live_includes_heart_rate():
    trainer = SimulatedTrainer()
    hr = _Hr()
    await hr.connect("uuid-hrm", "HRM-Pro")
    engine = WorkoutEngine(trainer, heart_rate=hr)
    assert engine.live.hr_connected is True
    assert engine.live.heart_rate_bpm == 131
    await hr.disconnect()
    assert engine.live.hr_connected is False
    assert engine.live.heart_rate_bpm is None


@dataclass
class _Settings:
    hr_auto_connect: bool = True
    hr_device_id: str | None = "uuid-hrm"
    hr_device_name: str | None = "HRM-Pro"
    ftp_w: int = 200
    trainer_mode: str = "simulated"
    trainer_host: str | None = None
    trainer_port: int = 36866
    allow_simulated: bool = True
    auto_connect: bool = False
    discover_timeout_s: float = 1.0


def _app(hr: Any, settings: _Settings | None = None) -> Any:
    settings = settings or _Settings()
    state = MagicMock()
    state.settings = settings
    state.heart_rate = hr
    state.repo = MagicMock()
    state.hr_autoconnect = HeartRateAutoconnect(get_app=lambda: state, interval_s=5)
    return state


@pytest.mark.asyncio
async def test_hr_autoconnect_uses_saved_id_and_pauses():
    hr = _Hr()
    state = _app(hr)
    svc: HeartRateAutoconnect = state.hr_autoconnect
    assert await svc.try_connect_now() is True
    assert hr.connected is True
    assert hr.device_id == "uuid-hrm"
    svc.pause()
    await hr.disconnect()
    assert await svc.try_connect_now() is False
    assert hr.connected is False


@pytest.mark.asyncio
async def test_hr_routes_hidden_off_macos_link():
    state = _app(NullHeartRate())
    req = MagicMock()
    req.app.state = state
    with pytest.raises(HTTPException) as exc:
        await routes_mod.hr_discover(req)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_hr_connect_persists_and_disconnect_pauses():
    hr = _Hr()
    state = _app(hr, _Settings(hr_device_id=None, hr_device_name=None))
    state.hr_autoconnect.pause()
    req = MagicMock()
    req.app.state = state

    found = await routes_mod.hr_discover(req)
    assert found["count"] == 1
    assert state.settings.hr_device_id == "uuid-hrm"

    body = routes_mod.HeartRateConnectBody(device_id="uuid-hrm", name="HRM-Pro")
    connected = await routes_mod.hr_connect(req, body)
    assert connected["connected"] is True
    assert connected["already_connected"] is False
    assert state.hr_autoconnect.paused is False
    state.repo.save_settings.assert_called()

    dropped = await routes_mod.hr_disconnect(req)
    assert dropped["was_connected"] is True
    assert dropped["connected"] is False
    assert hr.connected is False
    assert state.hr_autoconnect.paused is True
