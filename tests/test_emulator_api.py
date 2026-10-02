"""Emulator API gating — 404 when not in simulated mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from kickr_pi.api import routes as routes_mod
from kickr_pi.engine.models import EngineState, LiveState
from kickr_pi.trainer.simulated import SimulatedTrainer


@dataclass
class FakeSettings:
    trainer_mode: str = "dircon"
    trainer_host: str | None = "192.168.1.1"
    trainer_port: int = 36866
    allow_simulated: bool = False
    ftp_w: int = 200
    port: int = 8080
    discover_timeout_s: float = 1.0
    auto_connect: bool = False


class FakeDirCon:
    connected = True
    endpoint = ("192.168.1.1", 36866)

    async def discover(self, timeout_s: float = 5.0) -> list:
        return []

    async def connect(self, host: str, port: int) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def request_control(self) -> None:
        pass


class FakeRequest:
    def __init__(self, trainer: Any, mode: str = "dircon") -> None:
        self.app = MagicMock()
        settings = FakeSettings(
            trainer_mode=mode, allow_simulated=(mode == "simulated")
        )
        engine = MagicMock()
        engine.live = LiveState(
            engine_state=EngineState.IDLE,
            trainer_connected=bool(getattr(trainer, "connected", False)),
        )

        async def _set_trainer(t: Any) -> None:
            self.app.state.trainer = t

        engine.set_trainer = _set_trainer
        self.app.state = MagicMock()
        self.app.state.settings = settings
        self.app.state.trainer = trainer
        self.app.state.engine = engine
        self.app.state.workout_source = MagicMock(
            authenticated=False, display_name=None
        )
        self.app.state.repo = MagicMock()


def test_require_emulator_rejects_dircon():
    req = FakeRequest(FakeDirCon(), mode="dircon")
    with pytest.raises(HTTPException) as exc:
        routes_mod._require_emulator(req.app.state)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_emulator_status_ok():
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    await trainer.request_control()
    req = FakeRequest(trainer, mode="simulated")
    body = await routes_mod.emulator_status(req)  # type: ignore[arg-type]
    assert body["mode"] == "simulated"
    assert "quick_stages" in body["presets"]
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_emulator_target():
    trainer = SimulatedTrainer(ramp_w_s=500.0, tick_s=0.05)
    req = FakeRequest(trainer, mode="simulated")
    out = await routes_mod.emulator_target(
        routes_mod.EmulatorTargetBody(watts=120), req  # type: ignore[arg-type]
    )
    assert out["ok"] is True
    assert out["target_w"] == 120
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_status_emulator_flag_false_for_dircon():
    req = FakeRequest(FakeDirCon(), mode="dircon")
    body = await routes_mod.status(req)  # type: ignore[arg-type]
    assert body["emulator"] is False
