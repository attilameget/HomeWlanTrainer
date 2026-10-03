"""Bluetooth Heart Rate Measurement (GATT 0x2A37) decoder.

Pure function — no bleak import — so unit tests and the Raspberry Pi
process never need CoreBluetooth.
"""

from __future__ import annotations

# Heart Rate service / Heart Rate Measurement characteristic.
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# Drop the ride number when notifications stop (strap asleep or out of range).
STALE_AFTER_S = 5.0


def parse_heart_rate_measurement(data: bytes | bytearray) -> int | None:
    """Return bpm, or None when the packet has no usable rate.

    Flags bit 0 selects uint8 vs uint16. Bits 1–2 are the sensor-contact
    field: 2 means the strap is not against the body, so the number is
    ignored. 0 bpm is treated as no reading.
    """
    if not data or len(data) < 2:
        return None
    flags = data[0]
    contact = (flags >> 1) & 0x03
    if contact == 0x02:
        return None
    if flags & 0x01:
        if len(data) < 3:
            return None
        bpm = int.from_bytes(data[1:3], "little")
    else:
        bpm = int(data[1])
    if bpm < 1 or bpm > 250:
        return None
    return bpm
