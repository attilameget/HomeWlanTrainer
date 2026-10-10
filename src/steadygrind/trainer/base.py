"""TrainerLink protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

from steadygrind.trainer.ftms import BikeData, PowerRange


@dataclass(frozen=True)
class TrainerInfo:
    name: str
    host: str
    port: int
    serial: str | None = None


@runtime_checkable
class TrainerLink(Protocol):
    async def discover(self, timeout_s: float = 5.0) -> list[TrainerInfo]: ...

    async def connect(self, host: str, port: int) -> None: ...

    async def disconnect(self) -> None: ...

    @property
    def connected(self) -> bool: ...

    async def request_control(self) -> None: ...

    async def set_target_power(self, watts: int) -> None: ...

    async def set_resistance(self, level_tenths: int) -> None: ...

    async def start_resume(self) -> None: ...

    async def stop_pause(self, pause: bool = True) -> None: ...

    async def read_power_range(self) -> PowerRange: ...

    def live_metrics(self) -> AsyncIterator[BikeData]: ...
