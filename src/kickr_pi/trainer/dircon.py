"""Wahoo Direct Connect TrainerLink implementation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from kickr_pi.trainer.base import TrainerInfo
from kickr_pi.trainer.dircon_proto import (
    DirConBuffer,
    DirConMessage,
    MessageId,
    ResponseCode,
)
from kickr_pi.trainer.discover import discover_dircon
from kickr_pi.trainer import ftms

logger = logging.getLogger(__name__)


class DirConTrainer:
    """FTMS over Wahoo Direct Connect TCP."""

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._seq = 0
        self._buf = DirConBuffer()
        self._pending: dict[int, asyncio.Future[DirConMessage]] = {}
        self._metrics: asyncio.Queue[ftms.BikeData] = asyncio.Queue(maxsize=32)
        self._reader_task: asyncio.Task[None] | None = None
        self._connected = False
        self._host: str | None = None
        self._port: int | None = None
        self._power_range = ftms.PowerRange(0, 1000, 1)
        self._char_props: dict[UUID, int] = {}

    @property
    def endpoint(self) -> tuple[str, int] | None:
        if self._connected and self._host is not None and self._port is not None:
            return self._host, self._port
        return None

    async def discover(self, timeout_s: float = 5.0) -> list[TrainerInfo]:
        return await discover_dircon(timeout_s)

    async def connect(self, host: str, port: int) -> None:
        # Already on this trainer — Direct Connect is 1:1, keep the session.
        if self._connected and self._host == host and self._port == port:
            logger.info("already connected to %s:%s", host, port)
            return

        if self._connected:
            await self.disconnect()
            # KICKR needs a moment before accepting a new TCP client
            await asyncio.sleep(1.5)

        logger.info("connecting DirCon to %s:%s", host, port)
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                self._reader, self._writer = await asyncio.open_connection(host, port)
                self._connected = True
                self._host = host
                self._port = port
                self._reader_task = asyncio.create_task(self._read_loop())
                await self._discover_gatt()
                await self._enable_notifications(ftms.INDOOR_BIKE_DATA, notify=True)
                await self._enable_notifications(ftms.FMCP, indicate=True)
                await self._enable_notifications(ftms.FM_STATUS, notify=True)
                try:
                    raw = await self._read_characteristic(ftms.SUPPORTED_POWER_RANGE)
                    parsed = ftms.decode_supported_power_range(raw)
                    if parsed:
                        self._power_range = parsed
                except Exception as exc:  # noqa: BLE001
                    logger.warning("could not read power range: %s", exc)
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("connect attempt %s failed: %s", attempt, exc)
                await self.disconnect()
                await asyncio.sleep(1.0 * attempt)
        assert last_exc is not None
        raise last_exc

    async def disconnect(self) -> None:
        self._connected = False
        self._host = None
        self._port = None
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._writer = None
        self._reader = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("disconnected"))
        self._pending.clear()

    @property
    def connected(self) -> bool:
        return self._connected

    async def request_control(self) -> None:
        await self._write_cp(
            ftms.encode_request_control(),
            ftms.ControlPointOpcode.REQUEST_CONTROL,
        )

    async def set_target_power(self, watts: int) -> None:
        watts = max(self._power_range.min_w, min(self._power_range.max_w, watts))
        await self._write_cp(
            ftms.encode_set_target_power(watts),
            ftms.ControlPointOpcode.SET_TARGET_POWER,
        )

    async def set_resistance(self, level_tenths: int) -> None:
        await self._write_cp(
            ftms.encode_set_resistance(level_tenths),
            ftms.ControlPointOpcode.SET_TARGET_RESISTANCE,
        )

    async def start_resume(self) -> None:
        await self._write_cp(
            ftms.encode_start_resume(),
            ftms.ControlPointOpcode.START_OR_RESUME,
        )

    async def stop_pause(self, pause: bool = True) -> None:
        kind = ftms.StopPauseParam.PAUSE if pause else ftms.StopPauseParam.STOP
        await self._write_cp(
            ftms.encode_stop_pause(kind),
            ftms.ControlPointOpcode.STOP_OR_PAUSE,
        )

    async def read_power_range(self) -> ftms.PowerRange:
        return self._power_range

    async def live_metrics(self) -> AsyncIterator[ftms.BikeData]:
        while self._connected:
            yield await self._metrics.get()

    async def _discover_gatt(self) -> None:
        resp = await self._request(
            DirConMessage(identifier=MessageId.DISCOVER_SERVICES, is_request=True)
        )
        services = list(resp.additional_uuids)
        logger.info("DirCon services: %s", [str(u) for u in services])
        # Always probe FTMS even if the trainer omitted it from the list
        for svc in (ftms.FTMS_SERVICE, ftms.CPS_SERVICE):
            if svc not in services:
                services.append(svc)
        for svc in services:
            try:
                chars = await self._request(
                    DirConMessage(
                        identifier=MessageId.DISCOVER_CHARACTERISTICS,
                        uuid=svc,
                        is_request=True,
                    )
                )
                for i, cu in enumerate(chars.additional_uuids):
                    prop = (
                        chars.additional_data[i]
                        if i < len(chars.additional_data)
                        else 0
                    )
                    self._char_props[cu] = prop
                logger.info(
                    "chars for %s: %s",
                    svc,
                    [str(u) for u in chars.additional_uuids],
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("char discovery for %s failed: %s", svc, exc)

    async def _enable_notifications(
        self, char: UUID, *, notify: bool = False, indicate: bool = False
    ) -> None:
        value = 0
        if notify:
            value |= 0x01
        if indicate:
            value |= 0x02
        await self._request(
            DirConMessage(
                identifier=MessageId.ENABLE_NOTIFICATIONS,
                uuid=char,
                additional_data=bytes([value]),
                is_request=True,
            )
        )

    async def _read_characteristic(self, char: UUID) -> bytes:
        resp = await self._request(
            DirConMessage(
                identifier=MessageId.READ_CHARACTERISTIC,
                uuid=char,
                is_request=True,
            )
        )
        return resp.additional_data

    async def _write_cp(self, payload: bytes, expect_opcode: int) -> None:
        del expect_opcode  # used when we wire indication wait
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                await self._request(
                    DirConMessage(
                        identifier=MessageId.WRITE_CHARACTERISTIC,
                        uuid=ftms.FMCP,
                        additional_data=payload,
                        is_request=True,
                    ),
                    timeout=2.0,
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                await asyncio.sleep(0.2)
        assert last_exc is not None
        raise last_exc

    async def _request(
        self, msg: DirConMessage, timeout: float = 5.0
    ) -> DirConMessage:
        if not self._writer:
            raise ConnectionError("not connected")
        self._seq = (self._seq + 1) % 256
        msg.sequence = self._seq
        msg.is_request = True
        msg.response_code = ResponseCode.SUCCESS
        fut: asyncio.Future[DirConMessage] = asyncio.get_running_loop().create_future()
        self._pending[msg.sequence] = fut
        self._writer.write(msg.encode())
        await self._writer.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(msg.sequence, None)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while self._connected:
                data = await self._reader.read(4096)
                if not data:
                    raise ConnectionError("trainer closed connection")
                for msg in self._buf.feed(data):
                    await self._handle_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("DirCon read loop ended: %s", exc)
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(exc)

    async def _handle_message(self, msg: DirConMessage) -> None:
        if msg.identifier == MessageId.UNSOLICITED_NOTIFICATION and msg.uuid:
            if msg.uuid == ftms.INDOOR_BIKE_DATA:
                bike = ftms.decode_indoor_bike_data(msg.additional_data)
                try:
                    self._metrics.put_nowait(bike)
                except asyncio.QueueFull:
                    try:
                        self._metrics.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._metrics.put_nowait(bike)
            elif msg.uuid == ftms.FMCP:
                resp = ftms.decode_control_point_response(msg.additional_data)
                logger.debug("FMCP response: %s", resp)
            return

        fut = self._pending.get(msg.sequence)
        if fut and not fut.done():
            fut.set_result(msg)


async def create_trainer(mode: str) -> DirConTrainer | object:
    from kickr_pi.trainer.simulated import SimulatedTrainer

    if mode == "dircon":
        return DirConTrainer()
    return SimulatedTrainer()
