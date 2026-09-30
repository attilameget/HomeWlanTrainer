"""FTMS (Fitness Machine Service) encode/decode – pure, unit-tested."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from uuid import UUID

# 16-bit Bluetooth SIG UUIDs expanded to 128-bit base
_BT_BASE = "0000{short:04x}-0000-1000-8000-00805f9b34fb"


def sig_uuid(short: int) -> UUID:
    return UUID(_BT_BASE.format(short=short))


FTMS_SERVICE = sig_uuid(0x1826)
CPS_SERVICE = sig_uuid(0x1818)

FMCP = sig_uuid(0x2AD9)  # Fitness Machine Control Point
INDOOR_BIKE_DATA = sig_uuid(0x2AD2)
FM_STATUS = sig_uuid(0x2ADA)
SUPPORTED_POWER_RANGE = sig_uuid(0x2AD8)
CYCLING_POWER_MEASUREMENT = sig_uuid(0x2A63)


class ControlPointOpcode(IntEnum):
    REQUEST_CONTROL = 0x00
    RESET = 0x01
    SET_TARGET_RESISTANCE = 0x04
    SET_TARGET_POWER = 0x05
    START_OR_RESUME = 0x07
    STOP_OR_PAUSE = 0x08
    RESPONSE = 0x80


class StopPauseParam(IntEnum):
    STOP = 0x01
    PAUSE = 0x02


class ResultCode(IntEnum):
    SUCCESS = 0x01
    NOT_SUPPORTED = 0x02
    INVALID_PARAMETER = 0x03
    OPERATION_FAILED = 0x04
    CONTROL_NOT_PERMITTED = 0x05


@dataclass(frozen=True)
class PowerRange:
    min_w: int
    max_w: int
    increment_w: int = 1


@dataclass(frozen=True)
class BikeData:
    """Parsed Indoor Bike Data notification."""

    speed_kph: float | None = None
    cadence_rpm: float | None = None
    power_w: int | None = None


@dataclass(frozen=True)
class ControlPointResponse:
    request_opcode: int
    result_code: int


def encode_request_control() -> bytes:
    return bytes([ControlPointOpcode.REQUEST_CONTROL])


def encode_reset() -> bytes:
    return bytes([ControlPointOpcode.RESET])


def encode_set_target_power(watts: int) -> bytes:
    watts = max(-32768, min(32767, int(watts)))
    return bytes([ControlPointOpcode.SET_TARGET_POWER]) + watts.to_bytes(
        2, "little", signed=True
    )


def encode_set_resistance(level_tenths: int) -> bytes:
    """Resistance in 0.1 % steps (uint8)."""
    level = max(0, min(255, int(level_tenths)))
    return bytes([ControlPointOpcode.SET_TARGET_RESISTANCE, level])


def encode_start_resume() -> bytes:
    return bytes([ControlPointOpcode.START_OR_RESUME])


def encode_stop_pause(kind: StopPauseParam) -> bytes:
    return bytes([ControlPointOpcode.STOP_OR_PAUSE, int(kind)])


def decode_control_point_response(payload: bytes) -> ControlPointResponse | None:
    if len(payload) < 3 or payload[0] != ControlPointOpcode.RESPONSE:
        return None
    return ControlPointResponse(request_opcode=payload[1], result_code=payload[2])


def decode_supported_power_range(payload: bytes) -> PowerRange | None:
    if len(payload) < 6:
        return None
    return PowerRange(
        min_w=int.from_bytes(payload[0:2], "little", signed=True),
        max_w=int.from_bytes(payload[2:4], "little", signed=True),
        increment_w=int.from_bytes(payload[4:6], "little", signed=False),
    )


def decode_indoor_bike_data(payload: bytes) -> BikeData:
    """Parse FTMS Indoor Bike Data (0x2AD2). Flags in first 2 bytes, little-endian."""
    if len(payload) < 2:
        return BikeData()

    flags = int.from_bytes(payload[0:2], "little")
    offset = 2
    speed_kph: float | None = None
    cadence_rpm: float | None = None
    power_w: int | None = None

    # Bit 0: more data / instantaneous speed present when cleared is inverted in some
    # trainers; FTMS: bit0=0 means Instantaneous Speed present.
    if (flags & 0x0001) == 0:
        if offset + 2 <= len(payload):
            raw = int.from_bytes(payload[offset : offset + 2], "little")
            speed_kph = raw / 100.0
            offset += 2

    # Bit 1: Average Speed – skip 2 bytes if set
    if flags & 0x0002:
        offset += 2

    # Bit 2: Instantaneous Cadence (uint16, 1/2 rpm)
    if flags & 0x0004:
        if offset + 2 <= len(payload):
            raw = int.from_bytes(payload[offset : offset + 2], "little")
            cadence_rpm = raw / 2.0
            offset += 2

    # Bit 3: Average Cadence
    if flags & 0x0008:
        offset += 2

    # Bit 4: Total Distance (uint24)
    if flags & 0x0010:
        offset += 3

    # Bit 5: Resistance Level
    if flags & 0x0020:
        offset += 2

    # Bit 6: Instantaneous Power (sint16)
    if flags & 0x0040:
        if offset + 2 <= len(payload):
            power_w = int.from_bytes(payload[offset : offset + 2], "little", signed=True)
            offset += 2

    return BikeData(speed_kph=speed_kph, cadence_rpm=cadence_rpm, power_w=power_w)
