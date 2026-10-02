"""Simulated / emulator trainer for desk development and tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from kickr_pi.trainer.base import TrainerInfo
from kickr_pi.trainer.ftms import BikeData, PowerRange


@dataclass(frozen=True)
class PresetSegment:
    """One piece of an emulator-only power script (not part of TrainerLink)."""

    kind: str  # hold | ramp | pause
    duration_s: float
    watts: int | None = None
    end_watts: int | None = None


# Short desk presets — durations keep total under ~90s
PRESETS: dict[str, list[PresetSegment]] = {
    "quick_stages": [
        PresetSegment("hold", 10.0, watts=80),
        PresetSegment("ramp", 15.0, watts=80, end_watts=180),
        PresetSegment("hold", 10.0, watts=180),
        PresetSegment("pause", 5.0),
        PresetSegment("ramp", 10.0, watts=180, end_watts=100),
        PresetSegment("hold", 5.0, watts=100),
    ],
    "ramp_up_down": [
        PresetSegment("ramp", 15.0, watts=100, end_watts=250),
        PresetSegment("hold", 10.0, watts=250),
        PresetSegment("ramp", 20.0, watts=250, end_watts=100),
    ],
}


class SimulatedTrainer:
    """
    ERG emulator behind TrainerLink.

    Follows set_target_power with a configurable ramp rate. Emulator-only
    presets/scripts live on this class and must not be added to DirCon.
    """

    def __init__(
        self,
        cadence_rpm: float = 85.0,
        *,
        ramp_w_s: float = 60.0,
        tick_s: float = 0.25,
    ) -> None:
        self._connected = False
        self._has_control = False
        self._paused = False
        self._target_w = 0
        self._hold_target_w = 0  # target when not paused / not in preset override
        self._resistance = 0
        self._base_cadence = cadence_rpm
        self._cadence = cadence_rpm
        self._power = 0
        self._ramp_w_s = ramp_w_s
        self._tick_s = tick_s
        self._queue: asyncio.Queue[BikeData] = asyncio.Queue()
        self._tick_task: asyncio.Task[None] | None = None
        self._range = PowerRange(min_w=0, max_w=1000, increment_w=1)
        self._host = "127.0.0.1"
        self._port = 36866
        # When True, desk Set watts wins over engine ERG/keepalive until cleared
        self._desk_hold = False

        # Emulator-only preset state
        self._preset_name: str | None = None
        self._preset_segments: list[PresetSegment] = []
        self._preset_index = 0
        self._preset_elapsed = 0.0
        self._preset_task: asyncio.Task[None] | None = None

    @property
    def endpoint(self) -> tuple[str, int] | None:
        if not self._connected:
            return None
        return (self._host, self._port)

    @property
    def emulator(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {
            "mode": "simulated",
            "connected": self._connected,
            "paused": self._paused,
            "target_w": self._target_w,
            "power_w": self._power,
            "cadence_rpm": self._cadence,
            "preset_name": self._preset_name,
            "desk_hold": self._desk_hold,
            "presets": list(PRESETS.keys()),
        }

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
        self._host = host or "127.0.0.1"
        self._port = port or 36866
        self._connected = True
        if self._tick_task is None:
            self._tick_task = asyncio.create_task(self._tick_loop())

    async def disconnect(self) -> None:
        self._connected = False
        self._has_control = False
        await self._cancel_preset()
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
        # Desk Set watts is sticky: ignore engine ERG / keepalive until unlocked
        if self._desk_hold and self._preset_name is None:
            return
        await self._cancel_preset()
        clamped = max(self._range.min_w, min(self._range.max_w, int(watts)))
        self._hold_target_w = clamped
        if not self._paused:
            self._target_w = clamped

    async def set_resistance(self, level_tenths: int) -> None:
        if not self._has_control:
            raise RuntimeError("no control")
        if self._desk_hold and self._preset_name is None:
            return
        await self._cancel_preset()
        self._resistance = level_tenths
        self._hold_target_w = 0
        if not self._paused:
            self._target_w = 0

    async def start_resume(self) -> None:
        self._paused = False
        if self._preset_name is None:
            self._target_w = self._hold_target_w

    async def stop_pause(self, pause: bool = True) -> None:
        if pause:
            self._paused = True
            self._target_w = 0
        else:
            self._paused = False
            if self._preset_name is None:
                self._target_w = self._hold_target_w

    async def read_power_range(self) -> PowerRange:
        return self._range

    async def live_metrics(self) -> AsyncIterator[BikeData]:
        while self._connected:
            data = await self._queue.get()
            yield data

    # --- Emulator-only control (not on TrainerLink) ---

    async def emulator_set_target(self, watts: int) -> None:
        """Desk control: hold watts continuously (engine ERG will not overwrite)."""
        if not self._connected:
            await self.connect("127.0.0.1", 36866)
        if not self._has_control:
            await self.request_control()
        await self._cancel_preset()
        clamped = max(self._range.min_w, min(self._range.max_w, int(watts)))
        self._desk_hold = True
        self._hold_target_w = clamped
        if not self._paused:
            self._target_w = clamped

    async def emulator_follow_engine(self) -> None:
        """Clear desk hold so workout ERG / keepalive drives the emulator again."""
        self._desk_hold = False

    async def emulator_pause(self) -> None:
        await self.stop_pause(pause=True)

    async def emulator_resume(self) -> None:
        await self.start_resume()

    async def run_preset(self, name: str) -> None:
        if name not in PRESETS:
            raise ValueError(f"unknown preset: {name}")
        if not self._connected:
            await self.connect("127.0.0.1", 36866)
        if not self._has_control:
            await self.request_control()
        await self._cancel_preset()
        self._desk_hold = False
        self._preset_name = name
        self._preset_segments = list(PRESETS[name])
        self._preset_index = 0
        self._preset_elapsed = 0.0
        self._paused = False
        self._apply_preset_segment(self._preset_segments[0], 0.0)
        self._preset_task = asyncio.create_task(self._preset_loop())

    async def _cancel_preset(self) -> None:
        self._preset_name = None
        self._preset_segments = []
        self._preset_index = 0
        self._preset_elapsed = 0.0
        if self._preset_task is not None:
            self._preset_task.cancel()
            try:
                await self._preset_task
            except asyncio.CancelledError:
                pass
            self._preset_task = None

    def _apply_preset_segment(self, seg: PresetSegment, elapsed: float) -> None:
        if seg.kind == "pause":
            self._paused = True
            self._target_w = 0
            return
        self._paused = False
        if seg.kind == "hold":
            self._target_w = int(seg.watts or 0)
            self._hold_target_w = self._target_w
            return
        if seg.kind == "ramp":
            start = float(seg.watts or 0)
            end = float(seg.end_watts if seg.end_watts is not None else start)
            if seg.duration_s <= 0:
                self._target_w = int(end)
            else:
                t = min(1.0, elapsed / seg.duration_s)
                self._target_w = int(round(start + (end - start) * t))
            self._hold_target_w = self._target_w

    async def _preset_loop(self) -> None:
        try:
            while self._connected and self._preset_name and self._preset_segments:
                await asyncio.sleep(self._tick_s)
                if self._preset_index >= len(self._preset_segments):
                    break
                seg = self._preset_segments[self._preset_index]
                self._preset_elapsed += self._tick_s
                self._apply_preset_segment(seg, self._preset_elapsed)
                if self._preset_elapsed >= seg.duration_s:
                    self._preset_index += 1
                    self._preset_elapsed = 0.0
                    if self._preset_index >= len(self._preset_segments):
                        break
                    self._apply_preset_segment(
                        self._preset_segments[self._preset_index], 0.0
                    )
            self._preset_name = None
            self._preset_segments = []
            self._preset_index = 0
            self._preset_elapsed = 0.0
            self._preset_task = None
            # Keep the last preset watts until engine or desk takes over
            self._desk_hold = True
        except asyncio.CancelledError:
            raise

    async def _tick_loop(self) -> None:
        try:
            while self._connected:
                step = max(1, int(round(self._ramp_w_s * self._tick_s)))
                if self._paused or self._target_w <= 0:
                    self._power = max(0, self._power - max(step, 5))
                    cadence = 0.0 if self._power == 0 else self._base_cadence * 0.5
                else:
                    delta = self._target_w - self._power
                    if abs(delta) <= step:
                        self._power = self._target_w
                    else:
                        self._power += step if delta > 0 else -step
                    cadence = self._base_cadence
                self._cadence = cadence
                await self._queue.put(
                    BikeData(
                        speed_kph=cadence * 0.4,
                        cadence_rpm=cadence,
                        power_w=self._power,
                    )
                )
                await asyncio.sleep(self._tick_s)
        except asyncio.CancelledError:
            raise
