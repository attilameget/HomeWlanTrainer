"""Reconnect a saved heart-rate strap without scanning."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class HeartRateAutoconnect:
    """Connect to the saved strap id while hr_auto_connect is on.

    Manual Disconnect pauses attempts until Connect, or until Autoconnect
    is saved on again. This never scans — it uses the stored CoreBluetooth id.
    """

    def __init__(
        self,
        *,
        get_app: Callable[[], Any],
        interval_s: float = 15.0,
    ) -> None:
        self._get_app = get_app
        self._interval_s = max(5.0, float(interval_s))
        self._paused = False
        self._task: asyncio.Task[None] | None = None
        self._busy = False

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="hr-autoconnect")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def try_connect_now(self) -> bool:
        return await self._attempt()

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_s)
                await self._attempt()
        except asyncio.CancelledError:
            raise

    async def _attempt(self) -> bool:
        if self._busy or self._paused:
            return False
        app = self._get_app()
        if app is None:
            return False
        hr = getattr(app, "heart_rate", None)
        if hr is None or not getattr(hr, "supported", False):
            return False
        settings = app.settings
        if not bool(getattr(settings, "hr_auto_connect", False)):
            return False
        device_id = getattr(settings, "hr_device_id", None)
        if not device_id:
            return False
        if hr.connected:
            return True

        self._busy = True
        try:
            logger.info("heart rate autoconnect: connecting to saved strap…")
            await hr.connect(device_id, getattr(settings, "hr_device_name", None))
            logger.info("heart rate autoconnect: connected")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("heart rate autoconnect failed: %s", exc)
            return False
        finally:
            self._busy = False
