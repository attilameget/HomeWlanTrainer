from kickr_pi.trainer.ftms import (
    ControlPointOpcode,
    decode_control_point_response,
    decode_indoor_bike_data,
    decode_supported_power_range,
    encode_request_control,
    encode_set_resistance,
    encode_set_target_power,
    encode_start_resume,
    encode_stop_pause,
    StopPauseParam,
)


def test_encode_request_control():
    assert encode_request_control() == b"\x00"


def test_encode_set_target_power():
    assert encode_set_target_power(200) == b"\x05\xc8\x00"
    assert encode_set_target_power(-10) == b"\x05\xf6\xff"


def test_encode_set_resistance():
    assert encode_set_resistance(20) == b"\x04\x14"


def test_encode_start_and_stop():
    assert encode_start_resume() == bytes([ControlPointOpcode.START_OR_RESUME])
    assert encode_stop_pause(StopPauseParam.PAUSE) == b"\x08\x02"
    assert encode_stop_pause(StopPauseParam.STOP) == b"\x08\x01"


def test_decode_control_point_response():
    resp = decode_control_point_response(b"\x80\x00\x01")
    assert resp is not None
    assert resp.request_opcode == 0x00
    assert resp.result_code == 0x01


def test_decode_power_range():
    payload = (0).to_bytes(2, "little", signed=True)
    payload += (1000).to_bytes(2, "little", signed=True)
    payload += (1).to_bytes(2, "little", signed=False)
    rng = decode_supported_power_range(payload)
    assert rng is not None
    assert rng.min_w == 0
    assert rng.max_w == 1000
    assert rng.increment_w == 1


def test_decode_indoor_bike_data_speed_cadence_power():
    # flags: cadence + power, no instantaneous speed bit0=1 means speed absent
    flags = 0x0001 | 0x0004 | 0x0040
    payload = flags.to_bytes(2, "little")
    payload += (170).to_bytes(2, "little")  # cadence 85.0
    payload += (250).to_bytes(2, "little", signed=True)
    data = decode_indoor_bike_data(payload)
    assert data.cadence_rpm == 85.0
    assert data.power_w == 250
