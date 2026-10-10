"""Workout engine – owns the clock and is the only sender of trainer targets."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from steadygrind.engine.models import (
    EngineState,
    LiveState,
    Stage,
    Workout,
    demo_workout,
    manual_workout,
)
from steadygrind.rides.models import RideRecording, RideSample
from steadygrind.trainer.base import TrainerLink
from steadygrind.trainer.ftms import BikeData

logger = logging.getLogger(__name__)

LiveListener = Callable[[LiveState], Awaitable[None] | None]


class WorkoutEngine:
    def __init__(
        self,
        trainer: TrainerLink,
        *,
        ftp_w: int = 200,
        keepalive_s: float = 10.0,
        erg_zero_cadence_drop: float = 0.5,
        free_ride_resistance_tenths: int = 20,
        auto_pause_idle_s: float = 3.0,
        auto_resume_cadence_rpm: float = 5.0,
        clock: Callable[[], float] | None = None,
        heart_rate: Any | None = None,
    ) -> None:
        self._trainer = trainer
        self._heart_rate = heart_rate
        self._ftp_w = ftp_w
        self._keepalive_s = keepalive_s
        self._erg_drop = erg_zero_cadence_drop
        self._free_resistance = free_ride_resistance_tenths
        self._auto_pause_idle_s = max(1.0, float(auto_pause_idle_s))
        self._auto_resume_cadence = max(1.0, float(auto_resume_cadence_rpm))
        self._clock = clock or time.monotonic

        self._state = EngineState.IDLE
        self._workout: Workout | None = None
        self._stage_index = 0
        self._stage_elapsed = 0.0
        self._total_elapsed = 0.0
        self._intensity_pct = 100
        self._last_sent_w: int | None = None
        self._last_send_at = 0.0
        self._zero_cadence_s = 0.0
        self._cadence_drop_active = False
        self._pause_source: str | None = None  # "user" | "trainer"
        self._message: str | None = None

        self._power = 0
        self._cadence = 0.0
        self._speed = 0.0
        self._power_window: list[int] = []

        self._ride_started_at: datetime | None = None
        self._ride_samples: list[RideSample] = []
        self._ride_power_sum = 0
        self._ride_power_count = 0

        self._tick_task: asyncio.Task[None] | None = None
        self._metrics_task: asyncio.Task[None] | None = None
        self._listeners: list[LiveListener] = []
        self._lock = asyncio.Lock()

    def add_listener(self, listener: LiveListener) -> None:
        self._listeners.append(listener)

    async def set_trainer(self, trainer: TrainerLink) -> None:
        """Hot-swap trainer link (only when idle / finished). Restarts metrics loop."""
        if self._state in (
            EngineState.RUNNING,
            EngineState.PAUSED,
            EngineState.RECONNECTING,
            EngineState.LOADED,
        ):
            raise RuntimeError("cannot switch trainer while a session is active")
        if self._metrics_task is not None:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
            self._metrics_task = None
        self._trainer = trainer
        self._last_sent_w = None
        if trainer.connected:
            self._ensure_tasks()

    @property
    def live(self) -> LiveState:
        return self._build_live()

    def load(self, workout: Workout) -> None:
        if self._state in (
            EngineState.RUNNING,
            EngineState.PAUSED,
            EngineState.RECONNECTING,
        ):
            raise RuntimeError("cannot load while a session is active")
        # Allow starting a new ride after Finished without a full reset dance
        self._workout = workout
        self._stage_index = 0
        self._stage_elapsed = 0.0
        self._total_elapsed = 0.0
        self._intensity_pct = 100
        self._last_sent_w = None
        self._zero_cadence_s = 0.0
        self._cadence_drop_active = False
        self._pause_source = None
        self._message = None
        self._state = EngineState.LOADED

    async def prepare_new_session(self) -> None:
        """Stop a finished/active session so a new workout can be loaded."""
        if self._state in (
            EngineState.RUNNING,
            EngineState.PAUSED,
            EngineState.RECONNECTING,
            EngineState.FINISHED,
        ):
            await self.stop()
            self._state = EngineState.IDLE
            self._workout = None
            # Tick loop exits on FINISHED; clear so start() can spawn fresh tasks
            if self._tick_task and self._tick_task.done():
                self._tick_task = None
            if self._metrics_task and self._metrics_task.done():
                self._metrics_task = None

    def load_demo(self) -> Workout:
        w = demo_workout(self._ftp_w)
        self.load(w)
        return w

    def load_manual(self, target_w: int = 100) -> Workout:
        w = manual_workout(target_w)
        self.load(w)
        return w

    @property
    def is_manual(self) -> bool:
        return bool(self._workout and self._workout.id == "manual")

    async def start(self) -> None:
        async with self._lock:
            if self._state != EngineState.LOADED or not self._workout:
                raise RuntimeError("no workout loaded")
            if not self._trainer.connected:
                raise RuntimeError("trainer not connected")
            await self._trainer.request_control()
            await self._trainer.start_resume()
            self._state = EngineState.RUNNING
            self._last_sent_w = None
            self._ride_started_at = datetime.now(timezone.utc)
            self._ride_samples = []
            self._ride_power_sum = 0
            self._ride_power_count = 0
            await self._send_target(force=True)
            self._ensure_tasks()
        await self._publish()

    def take_ride_recording(self) -> RideRecording | None:
        """Snapshot for saving on Stop. None when elapsed is under 1 s."""
        if self._ride_started_at is None or self._total_elapsed < 1.0:
            return None
        avg: int | None = None
        if self._ride_power_count:
            avg = int(round(self._ride_power_sum / self._ride_power_count))
        name = self._workout.name if self._workout else None
        return RideRecording(
            started_at=self._ride_started_at,
            ended_at=datetime.now(timezone.utc),
            duration_s=float(self._total_elapsed),
            avg_power_w=avg,
            workout_name=name,
            samples=list(self._ride_samples),
        )

    async def pause(self) -> None:
        async with self._lock:
            if self._state != EngineState.RUNNING:
                return
            self._state = EngineState.PAUSED
            self._pause_source = "user"
            self._message = None
            await self._trainer.set_resistance(self._free_resistance)
            await self._trainer.stop_pause(pause=True)
            self._last_sent_w = None
        await self._publish()

    async def resume(self) -> None:
        async with self._lock:
            if self._state != EngineState.PAUSED:
                return
            await self._trainer.request_control()
            await self._trainer.start_resume()
            self._state = EngineState.RUNNING
            self._pause_source = None
            self._message = None
            self._zero_cadence_s = 0.0
            await self._send_target(force=True)
        await self._publish()

    async def stop(self) -> None:
        async with self._lock:
            if self._state in (EngineState.IDLE, EngineState.FINISHED):
                return
            self._state = EngineState.FINISHED
            try:
                await self._trainer.stop_pause(pause=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("stop command failed: %s", exc)
            self._last_sent_w = None
        await self._publish()

    async def skip(self) -> None:
        async with self._lock:
            if not self._workout or self._state not in (
                EngineState.RUNNING,
                EngineState.PAUSED,
            ):
                return
            if self._stage_index >= len(self._workout.stages) - 1:
                self._state = EngineState.FINISHED
            else:
                self._stage_index += 1
                self._stage_elapsed = 0.0
                if self._state == EngineState.RUNNING:
                    await self._send_target(force=True)
        await self._publish()

    async def previous(self) -> None:
        async with self._lock:
            if not self._workout or self._state not in (
                EngineState.RUNNING,
                EngineState.PAUSED,
            ):
                return
            if self._stage_index > 0:
                self._stage_index -= 1
            self._stage_elapsed = 0.0
            if self._state == EngineState.RUNNING:
                await self._send_target(force=True)
        await self._publish()

    async def adjust_intensity(self, delta: int) -> None:
        async with self._lock:
            self._intensity_pct = max(50, min(150, self._intensity_pct + delta))
            if self._state == EngineState.RUNNING:
                await self._send_target(force=True)
        await self._publish()

    async def set_target_watts(self, watts: int) -> None:
        """Set an absolute ERG target (manual mode, or override current stage)."""
        async with self._lock:
            if self._state not in (
                EngineState.RUNNING,
                EngineState.PAUSED,
                EngineState.LOADED,
            ):
                raise RuntimeError("no active session")
            stage = self._current_stage()
            if stage is None:
                raise RuntimeError("no stage")
            watts = max(0, min(2000, int(watts)))
            stage.target_mode = "erg"
            stage.target_w = watts
            stage.start_w = None
            stage.end_w = None
            stage.name = f"Hold {watts} W" if self.is_manual else stage.name
            self._intensity_pct = 100
            if self._state == EngineState.RUNNING:
                await self._send_target(force=True)
        await self._publish()

    async def adjust_target_watts(self, delta: int) -> None:
        stage = self._current_stage()
        current = 0
        if stage and stage.target_w is not None:
            current = int(stage.target_w * self._intensity_pct / 100.0)
        elif self._last_sent_w is not None:
            current = self._last_sent_w
        await self.set_target_watts(current + int(delta))

    async def on_connection_lost(self) -> None:
        async with self._lock:
            if self._state == EngineState.RUNNING:
                self._state = EngineState.RECONNECTING
        await self._publish()

    async def on_connection_restored(self) -> None:
        async with self._lock:
            if self._state == EngineState.RECONNECTING:
                await self._trainer.request_control()
                self._state = EngineState.RUNNING
                await self._send_target(force=True)
        await self._publish()

    def update_metrics(self, data: BikeData) -> None:
        if data.power_w is not None:
            self._power_window.append(data.power_w)
            self._power_window = self._power_window[-3:]
            self._power = int(sum(self._power_window) / len(self._power_window))
        if data.cadence_rpm is not None:
            self._cadence = data.cadence_rpm
        if data.speed_kph is not None:
            self._speed = data.speed_kph

    async def shutdown(self) -> None:
        for task in (self._tick_task, self._metrics_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._tick_task = None
        self._metrics_task = None

    def _ensure_tasks(self) -> None:
        if self._tick_task is None or self._tick_task.done():
            self._tick_task = asyncio.create_task(self._tick_loop())
        if self._metrics_task is None or self._metrics_task.done():
            self._metrics_task = asyncio.create_task(self._metrics_loop())

    async def _tick_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                async with self._lock:
                    if self._state == EngineState.RUNNING:
                        await self._on_tick()
                await self._publish()
                if self._state == EngineState.FINISHED:
                    break
        except asyncio.CancelledError:
            raise

    async def _metrics_loop(self) -> None:
        try:
            async for data in self._trainer.live_metrics():
                self.update_metrics(data)
                await self._sync_trainer_pause_state()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("metrics loop ended: %s", exc)
            await self.on_connection_lost()

    def _trainer_reports_paused(self) -> bool:
        return bool(getattr(self._trainer, "paused", False))

    async def _sync_trainer_pause_state(self) -> None:
        """Auto-pause/resume the workout when the trainer stops or starts again."""
        changed = False
        async with self._lock:
            trainer_paused = self._trainer_reports_paused()
            pedaling = self._cadence >= self._auto_resume_cadence

            if self._state == EngineState.RUNNING and trainer_paused:
                self._state = EngineState.PAUSED
                self._pause_source = "trainer"
                self._message = "Paused — trainer stopped"
                changed = True
            elif (
                self._state == EngineState.PAUSED
                and self._pause_source == "trainer"
                and not trainer_paused
                and pedaling
            ):
                self._state = EngineState.RUNNING
                self._pause_source = None
                self._message = None
                self._zero_cadence_s = 0.0
                try:
                    await self._send_target(force=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("auto-resume target failed: %s", exc)
                changed = True
        if changed:
            await self._publish()

    async def _on_tick(self) -> None:
        assert self._workout is not None
        stage = self._current_stage()

        pedaling = self._cadence >= self._auto_resume_cadence
        if not pedaling:
            self._zero_cadence_s += 1.0
        else:
            self._zero_cadence_s = 0.0
            self._cadence_drop_active = False

        # No pedaling → freeze workout clock (do not start / advance) until cadence returns
        if self._zero_cadence_s >= self._auto_pause_idle_s:
            self._state = EngineState.PAUSED
            self._pause_source = "trainer"
            self._message = "Paused — waiting for pedaling"
            return

        if not pedaling:
            return

        self._stage_elapsed += 1.0
        self._total_elapsed += 1.0
        self._append_ride_sample()

        if stage and stage.duration_s is not None and self._stage_elapsed >= stage.duration_s:
            if self._stage_index >= len(self._workout.stages) - 1:
                self._state = EngineState.FINISHED
                try:
                    await self._trainer.stop_pause(pause=False)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("finish stop failed: %s", exc)
                return
            self._stage_index += 1
            self._stage_elapsed = 0.0
            await self._send_target(force=True)
            return

        await self._send_target(force=False)

    async def _send_target(self, *, force: bool) -> None:
        stage = self._current_stage()
        if stage is None:
            return
        target = self._compute_target(stage)

        if self._zero_cadence_s >= 3.0 and stage.target_mode in ("erg", "ramp"):
            self._cadence_drop_active = True
            target = int(target * self._erg_drop)

        now = self._clock()
        if (
            not force
            and self._last_sent_w is not None
            and abs(target - self._last_sent_w) < 1
            and (now - self._last_send_at) < self._keepalive_s
        ):
            return

        try:
            if stage.target_mode == "resistance":
                await self._trainer.set_resistance(
                    stage.resistance_pct or self._free_resistance
                )
            else:
                await self._trainer.set_target_power(target)
            self._last_sent_w = target
            self._last_send_at = now
        except Exception as exc:  # noqa: BLE001
            logger.warning("send target failed: %s", exc)
            self._state = EngineState.RECONNECTING

    def _compute_target(self, stage: Stage) -> int:
        factor = self._intensity_pct / 100.0
        if (
            stage.target_mode == "ramp"
            and stage.start_w is not None
            and stage.end_w is not None
        ):
            dur = max(stage.duration_s or 1, 1)
            t = min(self._stage_elapsed / dur, 1.0)
            base = stage.start_w + (stage.end_w - stage.start_w) * t
        else:
            base = float(stage.target_w or 0)
        return max(0, int(round(base * factor)))

    def _current_stage(self) -> Stage | None:
        if not self._workout or not self._workout.stages:
            return None
        if self._stage_index >= len(self._workout.stages):
            return None
        return self._workout.stages[self._stage_index]

    def _build_live(self) -> LiveState:
        stage = self._current_stage()
        remaining: float | None = None
        total_remaining: float | None = None
        next_name: str | None = None
        if self._workout and stage:
            if stage.duration_s is not None:
                remaining = max(0.0, stage.duration_s - self._stage_elapsed)
            left = 0.0
            known = True
            for i, s in enumerate(self._workout.stages):
                if i < self._stage_index:
                    continue
                if s.duration_s is None:
                    known = False
                    break
                if i == self._stage_index:
                    left += max(0.0, s.duration_s - self._stage_elapsed)
                else:
                    left += s.duration_s
            if known:
                total_remaining = left
            if self._stage_index + 1 < len(self._workout.stages):
                next_name = self._workout.stages[self._stage_index + 1].name

        return LiveState(
            engine_state=self._state,
            workout_id=self._workout.id if self._workout else None,
            workout_name=self._workout.name if self._workout else None,
            stage_index=self._stage_index,
            stage_name=stage.name if stage else "",
            stage_count=len(self._workout.stages) if self._workout else 0,
            stage_elapsed_s=self._stage_elapsed,
            stage_remaining_s=remaining,
            total_elapsed_s=self._total_elapsed,
            total_remaining_s=total_remaining,
            target_w=self._last_sent_w
            or (self._compute_target(stage) if stage else 0),
            power_w=self._power,
            cadence_rpm=self._cadence,
            speed_kph=self._speed,
            intensity_pct=self._intensity_pct,
            next_stage_name=next_name,
            trainer_connected=self._trainer.connected,
            heart_rate_bpm=self._heart_rate_bpm(),
            hr_connected=bool(
                self._heart_rate is not None and self._heart_rate.connected
            ),
            message=self._message,
            manual=self.is_manual,
        )

    def _heart_rate_bpm(self) -> int | None:
        if self._heart_rate is None or not self._heart_rate.connected:
            return None
        bpm = self._heart_rate.bpm
        if bpm is None:
            return None
        return int(bpm)

    def _append_ride_sample(self) -> None:
        power = int(self._power)
        self._ride_power_sum += power
        self._ride_power_count += 1
        target = self._last_sent_w
        if target is None:
            stage = self._current_stage()
            target = self._compute_target(stage) if stage else 0
        self._ride_samples.append(
            RideSample(
                elapsed_s=float(self._total_elapsed),
                power_w=power,
                cadence_rpm=float(self._cadence),
                speed_kph=float(self._speed),
                heart_rate_bpm=self._heart_rate_bpm(),
                target_w=int(target or 0),
            )
        )

    async def _publish(self) -> None:
        live = self._build_live()
        for listener in list(self._listeners):
            try:
                result = listener(live)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.debug("listener error: %s", exc)
