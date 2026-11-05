"""Protocol tests with vectors captured from real EcoDrift pumps (05.11.2026). Run: python3 tests/test_protocol.py"""
from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "aquamedic_local"))
import protocol as pr  # noqa: E402

# EcoDrift status (393 bytes): on, random wave, flow 61, freq 100, feed 10 min, slot 0 = 00:00-00:00 classic 100/95
ECODRIFT_STATUS = bytes.fromhex("02413d640a645f00" + "0000000001645f00" + "ee" * 8 * 47 + "00")
PK = pr.PRODUCT_ECODRIFT


def test_framing():
    p = pr.build_packet(pr.CMD_DISCOVER)
    assert p == bytes.fromhex("0000000303000003")
    assert pr.parse_packet(p) == (pr.CMD_DISCOVER, b"")
    login = pr.frame_login("abcdefghij")
    assert login == bytes.fromhex("000000030f000008000a") + b"abcdefghij"
    # varint length for a long packet
    big = pr.build_packet(pr.CMD_P0_SEND, b"\x00" * 400)
    assert big[4:6] == bytes([0x80 | (403 & 0x7F), 403 >> 7])
    assert pr.parse_packet(big) == (pr.CMD_P0_SEND, b"\x00" * 400)
    # stream reassembly with a split packet and garbage in front
    buf = pr.PacketBuffer()
    assert buf.feed(b"\x01\x02" + big[:100]) == []
    assert buf.feed(big[100:] + p) == [(pr.CMD_P0_SEND, b"\x00" * 400), (pr.CMD_DISCOVER, b"")]


def test_replies():
    assert pr.parse_passcode(bytes.fromhex("000a") + b"0123456789") == "0123456789"
    assert pr.parse_passcode(bytes.fromhex("0000")) == ""
    assert pr.login_ok(b"\x00") and not pr.login_ok(b"\x01")
    disc = (
        struct.pack(">H", 22) + b"TestDid0000000000000AB"
        + struct.pack(">H", 6) + bytes.fromhex("020000000001")
        + struct.pack(">H", 8) + b"04020B25"
        + struct.pack(">H", 32) + PK.encode()
        + b"\x00\x00"
    )
    d = pr.parse_discovery(disc)
    assert d == {"did": "TestDid0000000000000AB", "mac": "02:00:00:00:00:01", "firmware": "04020B25", "product_key": PK}
    info = pr.parse_info(b"00ESP82604020B25030000010303000000000002" + b"\x00" * 11 + b" " + PK.encode())
    assert info == {"module": "00ESP826", "firmware": "04020B25", "product_key": PK}
    payload = struct.pack(">I", 1) + bytes([pr.ACTION_READ_REPLY]) + ECODRIFT_STATUS
    assert pr.status_from_p0(pr.CMD_P0_REPLY, payload, 393) == ECODRIFT_STATUS
    assert pr.status_from_p0(pr.CMD_P0_REPORT, bytes([pr.ACTION_REPORT]) + ECODRIFT_STATUS, 393) == ECODRIFT_STATUS
    assert pr.status_from_p0(pr.CMD_PONG, b"", 393) is None
    # change push of the EcoDrift module: 0x0093, sn 0, LV did, report
    push = b"\x00\x00\x00\x00" + struct.pack(">H", 22) + b"TestDid0000000000000AB" + bytes([pr.ACTION_REPORT]) + ECODRIFT_STATUS
    assert pr.status_from_p0(pr.CMD_P0_SEND, push, 393) == ECODRIFT_STATUS
    assert pr.status_from_p0(pr.CMD_P0_SEND, b"\x00\x00\x00\x02", 393) is None  # plain ack


def test_ecodrift_decode():
    s = pr.schema_for(PK)
    assert s.length == 393 and s.write_length == 392 and s.flag_bytes == 8
    raw = s.decode(ECODRIFT_STATUS)
    assert raw["SwitchON"] is True and raw["PulseTide"] is False and raw["Mode"] == 2
    assert raw["Linkage"] == 0 and raw["AutoMode"] == 1 and raw["Flow"] == 61
    d = pr.decode_status(PK, ECODRIFT_STATUS)
    assert d["power"] is True and d["mode"] == "random" and d["wave_form"] == "pulse"
    assert d["feed"] is False and d["timer"] is False and d["linkage"] == "independent"
    assert d["auto_mode"] == "classic" and d["flow"] == 61 and d["frequency"] == 100
    assert d["feed_time"] == 10 and d["auto_flow"] == 100 and d["auto_frequency"] == 95 and d["auto_feed_time"] == 0
    assert d["schedule"] == [{"slot": 0, "start": "00:00", "end": "00:00", "mode": "classic", "flow": 100, "frequency": 95, "wave_form": "pulse"}]
    assert d["fault_active"] is False and d["fault_list"] == [] and len(d["faults"]) == 7
    # a fault byte
    faulty = ECODRIFT_STATUS[:392] + bytes([0b00010100])
    d2 = pr.decode_status(PK, faulty)
    assert d2["fault_active"] and d2["fault_list"] == ["overtemperature", "locked_rotor"]


def test_ecodrift_encode():
    # flow alone is ignored by the pump, so the encoder adds the frequency (current value) as companion
    flags, data = pr.encode_values(PK, {"flow": 62}, base=ECODRIFT_STATUS)
    assert len(flags) == 8 and len(data) == 392
    assert flags == ((1 << 8) | (1 << 9)).to_bytes(8, "big") and flags[6] == 0x03
    assert data[2] == 62 and data[3] == 100 and data[:2] == ECODRIFT_STATUS[:2] and data[3:] == ECODRIFT_STATUS[3:392]
    flags, data = pr.encode_values(PK, {"frequency": 99}, base=ECODRIFT_STATUS)
    assert flags == (1 << 9).to_bytes(8, "big") and data[3] == 99 and data[2] == 61
    try:
        pr.encode_values(PK, {"flow": 62})
    except pr.ProtocolError:
        pass
    else:
        raise AssertionError("flow without status must fail")
    flags, data = pr.encode_values(PK, {"mode": "constant", "power": False}, base=ECODRIFT_STATUS)
    assert flags == ((1 << 5) | (1 << 0)).to_bytes(8, "big")
    word = int.from_bytes(data[:2], "big")
    assert word & 1 == 0 and (word >> 5) & 3 == 3 and (word >> 9) & 7 == 1  # AutoMode untouched
    flags, data = pr.encode_values(PK, {"feed": True, "feed_time": 5})
    assert data[:2] == bytes([0x00, 0x04]) and data[4] == 5 and flags == ((1 << 2) | (1 << 10)).to_bytes(8, "big")
    for bad in ({"flow": 101}, {"feed_time": 0}, {"mode": "wild"}, {"nope": 1}):
        try:
            pr.encode_values(PK, bad, base=ECODRIFT_STATUS)
        except pr.ProtocolError:
            pass
        else:
            raise AssertionError(bad)
    frame = pr.frame_write(7, flags, data)
    cmd, payload = pr.parse_packet(frame)
    assert cmd == pr.CMD_P0_SEND and payload[:5] == struct.pack(">I", 7) + b"\x01" and payload[5:13] == flags


def test_dc_runner():
    s = pr.schema_for(pr.PRODUCT_DC_RUNNER)
    assert s.length == 302 and s.write_length == 301 and s.flag_bytes == 8
    status = bytearray(302)
    status[0] = 0b0001_0011  # on, wireless, auto mode 1
    status[1] = 80
    status[2] = 10
    status[5:9] = bytes([20, 26, 11, 5])
    status[9:13] = bytes([0, 7, 30, 15])
    status[13:19] = bytes([8, 0, 20, 30, 1, 70])
    for i in range(1, 48):
        status[13 + 6 * i : 19 + 6 * i] = b"\xee" * 6
    d = pr.decode_status(pr.PRODUCT_DC_RUNNER, bytes(status))
    assert d["power"] and d["control"] == "wireless" and d["auto_mode"] == "auto" and d["speed"] == 80
    assert d["device_date"] == "2026-11-05" and d["device_time"] == "07:30:15"
    assert d["schedule"] == [{"slot": 0, "start": "08:00", "end": "20:30", "mode": "auto", "speed": 70}]
    # read only: no write path for the DC Runner until its writes are confirmed on hardware
    try:
        pr.encode_values(pr.PRODUCT_DC_RUNNER, {"speed": 50}, base=bytes(status))
    except pr.ProtocolError:
        pass
    else:
        raise AssertionError("DC Runner must be read only")
    assert pr.PRODUCT_DC_RUNNER not in pr.WRITE_MAP and pr.PRODUCT_ECODRIFT in pr.WRITE_MAP


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} tests passed")
