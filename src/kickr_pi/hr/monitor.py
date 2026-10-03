"""Heart-rate link: Bluetooth strap on macOS, no-op everywhere else."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from kickr_pi.hr.parse import (
    HEART_RATE_MEASUREMENT_UUID,
    HEART_RATE_SERVICE_UUID,
    STALE_AFTER_S,
    parse_heart_rate_measurement,
)

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 12.0


@dataclass(frozen=True)
class HeartRateDevice:
    device_id: str
    name: str


class HeartRateLink:
    """Discover, connect, and read bpm. `supported` is False off macOS."""

    supported: bool = False

    @property
    def connected(self) -> bool:
        return False

    @property
    def bpm(self) -> int | None:
        return None

    @property
    def device_id(self) -> str | None:
        return None

    @property
    def device_name(self) -> str | None:
        return None

    async def discover(self, timeout_s: float = 8.0) -> list[HeartRateDevice]:
        raise RuntimeError("heart rate is only available on macOS")

    async def connect(self, device_id: str, name: str | None = None) -> None:
        raise RuntimeError("heart rate is only available on macOS")

    async def disconnect(self) -> None:
        return None


class NullHeartRate(HeartRateLink):
    """Raspberry Pi and any non-macOS host. Routes answer 404."""


class BleHeartRateMonitor(HeartRateLink):
    """Standard BLE Heart Rate profile via CoreBluetooth (bleak).

    macOS exposes a UUID, not a MAC address. That id is what Settings stores.
    bleak is imported only when discover or connect runs.
    """

    supported = True

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._client: Any = None
        self._connected = False
        self._device_id: str | None = None
        self._device_name: str | None = None
        self._bpm: int | None = None
        self._last_at = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def bpm(self) -> int | None:
        if not self._connected or self._last_at <= 0.0:
            return None
        if self._clock() - self._last_at > STALE_AFTER_S:
            return None
        return self._bpm

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def device_name(self) -> str | None:
        return self._device_name

    def apply_measurement(self, data: bytes | bytearray) -> None:
        """Store one Heart Rate Measurement notification."""
        self._bpm = parse_heart_rate_measurement(data)
        self._last_at = self._clock()

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        self.apply_measurement(data)

    def _on_ble_disconnect(self, *_args: Any) -> None:
        self._connected = False
        self._bpm = None
        self._last_at = 0.0

    async def discover(self, timeout_s: float = 8.0) -> list[HeartRateDevice]:
        BleakScanner = _import_scanner()
        found = await BleakScanner.discover(
            timeout=max(1.0, float(timeout_s)),
            service_uuids=[HEART_RATE_SERVICE_UUID],
        )
        devices: list[HeartRateDevice] = []
        seen: set[str] = set()
        for dev in found:
            addr = getattr(dev, "address", None)
            if not addr or addr in seen:
                continue
            seen.add(addr)
            devices.append(
                HeartRateDevice(
                    device_id=str(addr),
                    name=(getattr(dev, "name", None) or "Heart rate monitor"),
                )
            )
        return devices

    async def connect(self, device_id: str, name: str | None = None) -> None:
        device_id = (device_id or "").strip()
        if not device_id:
            raise ValueError("heart rate device id is required")
        if (
            self._connected
            and self._device_id == device_id
            and self._client is not None
        ):
            if name:
                self._device_name = name
            return

        await self.disconnect()
        BleakClient = _import_client()
        client = BleakClient(device_id, disconnected_callback=self._on_ble_disconnect)
        try:
            await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT_S)
            await asyncio.wait_for(
                client.start_notify(HEART_RATE_MEASUREMENT_UUID, self._on_notify),
                timeout=CONNECT_TIMEOUT_S,
            )
        except Exception:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._on_ble_disconnect()
            raise

        self._client = client
        self._device_id = device_id
        self._device_name = name or self._device_name or "Heart rate monitor"
        self._connected = True
        self._bpm = None
        self._last_at = 0.0
        logger.info("heart rate connected to %s (%s)", self._device_name, device_id)

    async def disconnect(self) -> None:
        client = self._client
        self._client = None
        self._connected = False
        self._bpm = None
        self._last_at = 0.0
        if client is None:
            return
        try:
            await client.stop_notify(HEART_RATE_MEASUREMENT_UUID)
        except Exception:  # noqa: BLE001
            pass
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        logger.info("heart rate disconnected")


def _import_scanner() -> Any:
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise RuntimeError(
            "Bluetooth heart rate needs the bleak package (macOS build)"
        ) from exc
    return BleakScanner


def _import_client() -> Any:
    try:
        from bleak import BleakClient
    except ImportError as exc:
        raise RuntimeError(
            "Bluetooth heart rate needs the bleak package (macOS build)"
        ) from exc
    return BleakClient
