"""DirCon (Wahoo Direct Connect) framing – BLE GATT over TCP."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from uuid import UUID

HEADER_LENGTH = 6
PROTOCOL_VERSION = 1


class MessageId(IntEnum):
    DISCOVER_SERVICES = 0x01
    DISCOVER_CHARACTERISTICS = 0x02
    READ_CHARACTERISTIC = 0x03
    WRITE_CHARACTERISTIC = 0x04
    ENABLE_NOTIFICATIONS = 0x05
    UNSOLICITED_NOTIFICATION = 0x06
    UNKNOWN = 0x07
    ERROR = 0xFF


class ResponseCode(IntEnum):
    SUCCESS = 0x00
    UNKNOWN_MESSAGE_TYPE = 0x01
    UNEXPECTED_ERROR = 0x02
    SERVICE_NOT_FOUND = 0x03
    CHARACTERISTIC_NOT_FOUND = 0x04
    OPERATION_NOT_SUPPORTED = 0x05
    WRITE_FAILED = 0x06
    UNKNOWN_PROTOCOL = 0x07


# DirCon characteristic property flags
PROP_READ = 0x01
PROP_WRITE = 0x02
PROP_NOTIFY = 0x04
PROP_INDICATE = 0x08
PROP_WRITE_NR = 0x10


def uuid_to_bytes(u: UUID) -> bytes:
    """Encode UUID as 16 bytes in DirCon wire order (BLE little-endian style)."""
    return u.bytes_le


def bytes_to_uuid(data: bytes, offset: int = 0) -> UUID:
    return UUID(bytes_le=data[offset : offset + 16])


@dataclass
class DirConMessage:
    identifier: MessageId
    sequence: int = 0
    response_code: ResponseCode = ResponseCode.SUCCESS
    uuid: UUID | None = None
    additional_uuids: list[UUID] = field(default_factory=list)
    additional_data: bytes = b""
    is_request: bool = True
    version: int = PROTOCOL_VERSION

    def encode(self) -> bytes:
        payload = self._encode_payload()
        header = bytes(
            [
                self.version,
                int(self.identifier),
                self.sequence & 0xFF,
                int(self.response_code),
                (len(payload) >> 8) & 0xFF,
                len(payload) & 0xFF,
            ]
        )
        return header + payload

    def _encode_payload(self) -> bytes:
        mid = self.identifier
        if mid == MessageId.DISCOVER_SERVICES:
            if self.is_request:
                return b""
            out = bytearray()
            for u in self.additional_uuids:
                out.extend(uuid_to_bytes(u))
            return bytes(out)

        if mid == MessageId.DISCOVER_CHARACTERISTICS:
            if self.is_request:
                assert self.uuid is not None
                return uuid_to_bytes(self.uuid)
            assert self.uuid is not None
            out = bytearray(uuid_to_bytes(self.uuid))
            for i, u in enumerate(self.additional_uuids):
                out.extend(uuid_to_bytes(u))
                prop = self.additional_data[i] if i < len(self.additional_data) else 0
                out.append(prop)
            return bytes(out)

        if mid in (
            MessageId.READ_CHARACTERISTIC,
            MessageId.WRITE_CHARACTERISTIC,
            MessageId.ENABLE_NOTIFICATIONS,
            MessageId.UNSOLICITED_NOTIFICATION,
        ):
            assert self.uuid is not None
            return uuid_to_bytes(self.uuid) + self.additional_data

        return b""


def parse_message(data: bytes) -> tuple[DirConMessage | None, int]:
    """Parse one DirCon message from a buffer. Returns (message, bytes_consumed)."""
    if len(data) < HEADER_LENGTH:
        return None, 0

    version = data[0]
    identifier = MessageId(data[1])
    sequence = data[2]
    response_code = ResponseCode(data[3])
    length = (data[4] << 8) | data[5]

    if len(data) < HEADER_LENGTH + length:
        return None, 0

    body = data[HEADER_LENGTH : HEADER_LENGTH + length]
    consumed = HEADER_LENGTH + length
    msg = DirConMessage(
        identifier=identifier,
        sequence=sequence,
        response_code=response_code,
        version=version,
        is_request=False,
    )

    if identifier == MessageId.DISCOVER_SERVICES:
        if length == 0:
            msg.is_request = True
        elif length % 16 == 0:
            msg.additional_uuids = [
                bytes_to_uuid(body, i) for i in range(0, length, 16)
            ]
        else:
            return None, consumed

    elif identifier == MessageId.DISCOVER_CHARACTERISTICS:
        if length < 16:
            return None, consumed
        msg.uuid = bytes_to_uuid(body, 0)
        rest = length - 16
        if rest == 0:
            msg.is_request = True
        elif rest % 17 == 0:
            uuids: list[UUID] = []
            props = bytearray()
            for i in range(16, length, 17):
                uuids.append(bytes_to_uuid(body, i))
                props.append(body[i + 16])
            msg.additional_uuids = uuids
            msg.additional_data = bytes(props)
        else:
            return None, consumed

    elif identifier in (
        MessageId.READ_CHARACTERISTIC,
        MessageId.WRITE_CHARACTERISTIC,
        MessageId.ENABLE_NOTIFICATIONS,
        MessageId.UNSOLICITED_NOTIFICATION,
    ):
        if length < 16:
            return None, consumed
        msg.uuid = bytes_to_uuid(body, 0)
        msg.additional_data = body[16:]
        if identifier == MessageId.READ_CHARACTERISTIC and length == 16:
            msg.is_request = True
        if identifier == MessageId.ENABLE_NOTIFICATIONS and length > 16:
            msg.is_request = True
        if identifier == MessageId.WRITE_CHARACTERISTIC:
            msg.is_request = True

    return msg, consumed


class DirConBuffer:
    """Accumulate TCP bytes and yield complete DirCon messages."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[DirConMessage]:
        self._buf.extend(data)
        messages: list[DirConMessage] = []
        while True:
            msg, consumed = parse_message(bytes(self._buf))
            if consumed == 0:
                break
            del self._buf[:consumed]
            if msg is not None:
                messages.append(msg)
        return messages
