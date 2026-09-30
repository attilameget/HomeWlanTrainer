"""Simulated trainer for desk development and tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from kickr_pi.trainer.base import TrainerInfo
from kickr_pi.trainer.ftms import BikeData, PowerRange


class SimulatedTrainer:
    """ERG simulator: actual power tracks target with light noise; cadence fixed."""

    def __init__(self, cadence_rpm: float = 85.0) -> None:
        self._connected = False
        self._has_control = False
        self._target_w = 0
        self._resistance = 0
        self._cadence = cadence_rpm
        self._power = 0
        self._queue: asyncio.Queue[BikeData] = asyncio.Queue()
        self._tick_task: asyncio.Task[None] | None = None
        self._range = PowerRange(min_w=0, max_w=1000, increment_w=1)

    async def discover(self, timeout_s: float = 5.0) -> list[TrainerInfo]:
        return [
            TrainerInfo(
                name="Simulated KICKR",
                host="127.0.0.1",
                port=36866,
                serial="SIM0001",
            )
        ]

    async def connect(self, host: str, port: int) -> None:
        self._connected = True
        if self._tick_task is None:
            self._tick_task = asyncio.create_task(self._tick_loop())

    async def disconnect(self) -> None:
        self._connected = False
        self._has_control = False
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def request_control(self) -> None:
        if not self._connected:
            raise RuntimeError("not connected")
        self._has_control = True

    async def set_target_power(self, watts: int) -> None:
        if not self._has_control:
            raise RuntimeError("no control")
        self._target_w = max(self._range.min_w, min(self._range.max_w, watts))

    async def set_resistance(self, level_tenths: int) -> None:
        if not self._has_control:
            raise RuntimeError("no control")
        self._resistance = level_tenths
        self._target_w = 0

    async def start_resume(self) -> None:
        pass

    async def stop_pause(self, pause: bool = True) -> None:
        if pause:
            self._target_w = 0

    async def read_power_range(self) -> PowerRange:
        return self._range

    async def live_metrics(self) -> AsyncIterator[BikeData]:
        while self._connected:
            data = await self._queue.get()
            yield data

    async def _tick_loop(self) -> None:
        try:
            while self._connected:
                if self._target_w > 0:
                    # Ease toward target
                    delta = self._target_w - self._power
                    self._power += int(delta * 0.4) if abs(delta) > 1 else delta
                    cadence = self._cadence
                else:
                    self._power = max(0, self._power - 5)
                    cadence = 0.0 if self._power == 0 else self._cadence * 0.5
                await self._queue.put(
                    BikeData(
                        speed_kph=cadence * 0.4,
                        cadence_rpm=cadence,
                        power_w=self._power,
                    )
                )
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
