from uuid import UUID

from steadygrind.trainer.dircon_proto import (
    DirConBuffer,
    DirConMessage,
    MessageId,
    parse_message,
    uuid_to_bytes,
)
from steadygrind.trainer.ftms import FTMS_SERVICE


def test_discover_services_request_roundtrip():
    msg = DirConMessage(identifier=MessageId.DISCOVER_SERVICES, sequence=1, is_request=True)
    raw = msg.encode()
    assert raw[:6] == b"\x01\x01\x01\x00\x00\x00"
    parsed, consumed = parse_message(raw)
    assert consumed == len(raw)
    assert parsed is not None
    assert parsed.identifier == MessageId.DISCOVER_SERVICES
    assert parsed.is_request is True


def test_discover_services_response():
    msg = DirConMessage(
        identifier=MessageId.DISCOVER_SERVICES,
        sequence=1,
        is_request=False,
        additional_uuids=[FTMS_SERVICE],
    )
    raw = msg.encode()
    parsed, _ = parse_message(raw)
    assert parsed is not None
    assert len(parsed.additional_uuids) == 1
    assert parsed.additional_uuids[0] == FTMS_SERVICE


def test_write_characteristic():
    char = UUID("00002ad9-0000-1000-8000-00805f9b34fb")
    msg = DirConMessage(
        identifier=MessageId.WRITE_CHARACTERISTIC,
        sequence=3,
        uuid=char,
        additional_data=b"\x05\xc8\x00",
        is_request=True,
    )
    raw = msg.encode()
    assert raw[0:4] == b"\x01\x04\x03\x00"
    assert len(raw) == 6 + 16 + 3
    assert raw[6:22] == uuid_to_bytes(char)
    assert raw[6:22] == char.bytes
    parsed, _ = parse_message(raw)
    assert parsed is not None
    assert parsed.uuid == char
    assert parsed.additional_data == b"\x05\xc8\x00"


def test_ftms_service_uuid_roundtrip():
    msg = DirConMessage(
        identifier=MessageId.DISCOVER_SERVICES,
        sequence=1,
        is_request=False,
        additional_uuids=[FTMS_SERVICE],
    )
    raw = msg.encode()
    # Wire bytes for 0x1826 use RFC order (matches KICKR DirCon)
    assert raw[6:22] == FTMS_SERVICE.bytes
    parsed, _ = parse_message(raw)
    assert parsed is not None
    assert parsed.additional_uuids[0] == FTMS_SERVICE


def test_buffer_feeds_partial():
    msg = DirConMessage(identifier=MessageId.DISCOVER_SERVICES, sequence=2, is_request=True)
    raw = msg.encode()
    buf = DirConBuffer()
    assert buf.feed(raw[:3]) == []
    out = buf.feed(raw[3:])
    assert len(out) == 1
    assert out[0].sequence == 2
