"""Background autoconnect for Real KICKR when the trainer appears on the LAN."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class AutoconnectService:
    """Periodically discover/connect DirCon while auto_connect is enabled.

    Manual Disconnect pauses attempts until Connect, re-enable of the toggle,
    or process restart (startup still honors auto_connect).
    """

    def __init__(
        self,
        *,
        get_app: Callable[[], Any],
        connect_fn: Callable[[Any, Any], Awaitable[bool]],
        interval_s: float = 15.0,
    ) -> None:
        self._get_app = get_app
        self._connect_fn = connect_fn
        self._interval_s = max(5.0, float(interval_s))
        self._paused = False
        self._task: asyncio.Task[None] | None = None
        self._busy = False

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Stop trying after an intentional Disconnect (other apps can take DC)."""
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="trainer-autoconnect")

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
        """One-shot attempt (e.g. after enabling the toggle)."""
        return await self._attempt()

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_s)
                await self._attempt()
        except asyncio.CancelledError:
            raise

    async def _attempt(self) -> bool:
        if self._busy:
            return False
        app = self._get_app()
        if app is None:
            return False
        settings = app.settings
        if not bool(getattr(settings, "auto_connect", False)):
            return False
        if settings.trainer_mode != "dircon":
            return False
        if self._paused:
            return False
        if app.trainer.connected:
            return True
        live = app.engine.live
        if live.engine_state in ("running", "paused", "reconnecting", "loaded"):
            return False

        self._busy = True
        try:
            logger.info("autoconnect: looking for KICKR…")
            ok = await self._connect_fn(app.trainer, settings)
            if not ok and settings.trainer_host:
                # Saved host may be stale after DHCP — rediscover
                saved_host = settings.trainer_host
                saved_port = settings.trainer_port
                settings.trainer_host = None
                ok = await self._connect_fn(app.trainer, settings)
                if not ok:
                    settings.trainer_host = saved_host
                    settings.trainer_port = saved_port
            if ok:
                self._paused = False
                try:
                    await app.engine.set_trainer(app.trainer)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("autoconnect: engine rebind failed: %s", exc)
                logger.info("autoconnect: trainer connected")
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.warning("autoconnect attempt failed: %s", exc)
            return False
        finally:
            self._busy = False
