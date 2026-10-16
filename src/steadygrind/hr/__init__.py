"""Heart-rate monitor link. Bluetooth via bleak on macOS and Windows."""

from __future__ import annotations

import platform

from steadygrind.hr.monitor import (
    BleHeartRateMonitor,
    HeartRateDevice,
    HeartRateLink,
    NullHeartRate,
)

__all__ = [
    "BleHeartRateMonitor",
    "HeartRateDevice",
    "HeartRateLink",
    "NullHeartRate",
    "create_heart_rate",
]


def create_heart_rate() -> HeartRateLink:
    """Bleak on Darwin/Windows; a no-op link elsewhere."""
    if platform.system() in {"Darwin", "Windows"}:
        return BleHeartRateMonitor()
    return NullHeartRate()
