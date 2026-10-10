"""Autoconnect service unit tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from steadygrind.engine.models import EngineState, LiveState
from steadygrind.trainer.autoconnect import AutoconnectService


@dataclass
class FakeSettings:
    auto_connect: bool = True
    trainer_mode: str = "dircon"
    trainer_host: str | None = "192.168.1.10"
    trainer_port: int = 36866


@dataclass
class FakeTrainer:
    connected: bool = False


@dataclass
class FakeApp:
    settings: FakeSettings = field(default_factory=FakeSettings)
    trainer: FakeTrainer = field(default_factory=FakeTrainer)
    engine: Any = field(default_factory=MagicMock)


@pytest.mark.asyncio
async def test_autoconnect_skips_when_disabled():
    app = FakeApp()
    app.settings.auto_connect = False
    app.engine.live = LiveState(engine_state=EngineState.IDLE)
    connect = AsyncMock(return_value=True)
    svc = AutoconnectService(get_app=lambda: app, connect_fn=connect, interval_s=5)
    assert await svc.try_connect_now() is False
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_autoconnect_skips_when_paused_after_disconnect():
    app = FakeApp()
    app.engine.live = LiveState(engine_state=EngineState.IDLE)
    connect = AsyncMock(return_value=True)
    svc = AutoconnectService(get_app=lambda: app, connect_fn=connect, interval_s=5)
    svc.pause()
    assert await svc.try_connect_now() is False
    connect.assert_not_called()
    svc.resume()
    assert await svc.try_connect_now() is True
    connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_autoconnect_connects_and_rebinds_engine():
    app = FakeApp()
    app.engine.live = LiveState(engine_state=EngineState.IDLE)
    app.engine.set_trainer = AsyncMock()

    async def _connect(trainer: Any, settings: Any) -> bool:
        trainer.connected = True
        return True

    svc = AutoconnectService(get_app=lambda: app, connect_fn=_connect, interval_s=5)
    assert await svc.try_connect_now() is True
    app.engine.set_trainer.assert_awaited_once_with(app.trainer)


@pytest.mark.asyncio
async def test_autoconnect_rediscovers_when_saved_host_fails():
    app = FakeApp()
    app.engine.live = LiveState(engine_state=EngineState.IDLE)
    app.engine.set_trainer = AsyncMock()
    calls: list[str | None] = []

    async def _connect(trainer: Any, settings: Any) -> bool:
        calls.append(settings.trainer_host)
        if settings.trainer_host is None:
            settings.trainer_host = "192.168.1.99"
            trainer.connected = True
            return True
        return False

    svc = AutoconnectService(get_app=lambda: app, connect_fn=_connect, interval_s=5)
    assert await svc.try_connect_now() is True
    assert calls == ["192.168.1.10", None]
    assert app.settings.trainer_host == "192.168.1.99"


@pytest.mark.asyncio
async def test_autoconnect_skips_emulator_mode():
    app = FakeApp()
    app.settings.trainer_mode = "simulated"
    app.engine.live = LiveState(engine_state=EngineState.IDLE)
    connect = AsyncMock(return_value=True)
    svc = AutoconnectService(get_app=lambda: app, connect_fn=connect, interval_s=5)
    assert await svc.try_connect_now() is False
    connect.assert_not_called()
