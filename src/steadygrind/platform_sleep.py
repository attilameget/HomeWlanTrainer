"""Prevent host sleep / display dimming while a workout session is active."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

logger = logging.getLogger(__name__)

# Engine states that mean a ride session is in progress
ACTIVE_STATES = frozenset({"running", "paused", "reconnecting"})

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


class SleepGuard:
    """Hold a platform sleep assertion (macOS caffeinate / Windows execution state)."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._active = False
        system = platform.system()
        self._backend = {
            "Darwin": "darwin",
            "Windows": "windows",
        }.get(system)

    @property
    def active(self) -> bool:
        return self._active

    async def sync(self, engine_state: str) -> None:
        if engine_state in ACTIVE_STATES:
            await self.acquire()
        else:
            await self.release()

    async def acquire(self) -> None:
        if self._backend is None or self._active:
            return
        if self._backend == "darwin":
            await self._acquire_darwin()
        elif self._backend == "windows":
            self._acquire_windows()

    async def _acquire_darwin(self) -> None:
        try:
            # -d display, -i idle sleep, -m disk idle, -s system sleep (AC)
            self._proc = await asyncio.create_subprocess_exec(
                "caffeinate",
                "-dims",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._active = True
            logger.info("sleep guard on (caffeinate -dims, pid=%s)", self._proc.pid)
        except FileNotFoundError:
            logger.warning("caffeinate not found; cannot prevent Mac sleep")
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to start sleep guard: %s", exc)

    def _acquire_windows(self) -> None:
        try:
            import ctypes

            flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
            self._active = True
            logger.info("sleep guard on (SetThreadExecutionState)")
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to start Windows sleep guard: %s", exc)

    async def release(self) -> None:
        if not self._active:
            return
        if self._backend == "darwin":
            await self._release_darwin()
        elif self._backend == "windows":
            self._release_windows()
        else:
            self._active = False

    async def _release_darwin(self) -> None:
        proc = self._proc
        self._proc = None
        self._active = False
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        logger.info("sleep guard off")

    def _release_windows(self) -> None:
        self._active = False
        try:
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        except Exception:  # noqa: BLE001
            pass
        logger.info("sleep guard off")

    def on_live(self, live: Any) -> None:
        """Engine listener entry – schedule acquire/release from sync callback."""
        state = getattr(live, "engine_state", None)
        value = state.value if hasattr(state, "value") else str(state or "")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.sync(value))
