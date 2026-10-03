"""Heart-rate monitor link. Bluetooth is macOS-only."""

from __future__ import annotations

import platform

from kickr_pi.hr.monitor import (
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
    """Bleak/CoreBluetooth on Darwin; a no-op link on Raspberry Pi and elsewhere."""
    if platform.system() == "Darwin":
        return BleHeartRateMonitor()
    return NullHeartRate()
