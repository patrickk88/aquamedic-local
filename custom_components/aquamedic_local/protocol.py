"""Gizwits LAN protocol as spoken by Aqua Medic pumps (EcoDrift / SmartDrift, DC Runner).

Pure Python, no Home Assistant imports, so it can be unit tested on its own.

Wire format (TCP 12416 for control, UDP 12414 for discovery):
    00 00 00 03 | length (varint) | flag 00 | command (2 bytes) | payload
The pump reports its product key; each product has a public "datapoint" schema
that fixes the byte/bit layout of the status block (P0). The schemas of the two
known Aqua Medic products are embedded below as compact tables.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

HEADER = b"\x00\x00\x00\x03"
TCP_PORT = 12416
UDP_PORT = 12414

CMD_DISCOVER = 0x0003
CMD_DISCOVER_REPLY = 0x0004
CMD_PASSCODE_REQ = 0x0006
CMD_PASSCODE_RESP = 0x0007
CMD_LOGIN_REQ = 0x0008
CMD_LOGIN_RESP = 0x0009
CMD_INFO_REQ = 0x0013
CMD_INFO_RESP = 0x0014
CMD_PING = 0x0015
CMD_PONG = 0x0016
CMD_P0_REPORT = 0x0091  # pushed by the device when something changed
CMD_P0_SEND = 0x0093  # client -> device, 4-byte sequence number + action + data
CMD_P0_REPLY = 0x0094  # device -> client, answer to 0x0093

ACTION_WRITE = 0x01
ACTION_READ = 0x02
ACTION_READ_REPLY = 0x03
ACTION_REPORT = 0x04

PRODUCT_ECODRIFT = "63632f4902094055ab3fd994c0d612fa"  # EcoDrift x.3 / SmartDrift x.1 ("Current_Pump")
PRODUCT_DC_RUNNER = "00276aa006684c05805c297f60058c3d"  # DC Runner x.3 return / skimmer pump

MODEL_NAME = {
    PRODUCT_ECODRIFT: "EcoDrift / SmartDrift",
    PRODUCT_DC_RUNNER: "DC Runner",
}
MANUFACTURER = "Aqua Medic"

SLOTS = 48  # timer slots per pump
SLOT_EMPTY = 0xEE  # filler byte of an unused timer slot

# --- framing ---------------------------------------------------------------------


class ProtocolError(Exception):
    """Malformed packet."""


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def build_packet(cmd: int, payload: bytes = b"") -> bytes:
    body = b"\x00" + struct.pack(">H", cmd) + payload
    return HEADER + _varint(len(body)) + body


def parse_packet(data: bytes) -> tuple[int, bytes]:
    """One complete packet (UDP datagram) -> (command, payload)."""
    cmd, payload, used = _parse_prefix(data)
    if used is None:
        raise ProtocolError("incomplete packet")
    return cmd, payload


def _parse_prefix(data: bytes) -> tuple[int, bytes, int | None]:
    if len(data) < 5:
        return 0, b"", None
    if data[:4] != HEADER:
        raise ProtocolError("unexpected header")
    length, shift, i = 0, 0, 4
    while True:
        if i >= len(data):
            return 0, b"", None
        b = data[i]
        i += 1
        length |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            break
        if shift > 28:
            raise ProtocolError("length too long")
    if len(data) < i + length or length < 3:
        return 0, b"", None if len(data) < i + length else i + length
    body = data[i : i + length]
    return struct.unpack(">H", body[1:3])[0], body[3:], i + length


class PacketBuffer:
    """Reassembles packets from a TCP stream."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buf += data
        out: list[tuple[int, bytes]] = []
        while self._buf:
            if self._buf[:4] != HEADER[: min(4, len(self._buf))]:
                # resync on the next header
                idx = self._buf.find(HEADER, 1)
                if idx < 0:
                    self._buf.clear()
                    break
                del self._buf[:idx]
                continue
            cmd, payload, used = _parse_prefix(bytes(self._buf))
            if used is None:
                break
            del self._buf[:used]
            if payload or cmd:
                out.append((cmd, payload))
        return out


# --- requests --------------------------------------------------------------------


def frame_discover() -> bytes:
    return build_packet(CMD_DISCOVER)


def frame_passcode_request() -> bytes:
    return build_packet(CMD_PASSCODE_REQ)


def frame_login(passcode: str | bytes) -> bytes:
    pc = passcode.encode() if isinstance(passcode, str) else passcode
    return build_packet(CMD_LOGIN_REQ, struct.pack(">H", len(pc)) + pc)


def frame_info_request() -> bytes:
    return build_packet(CMD_INFO_REQ)


def frame_ping() -> bytes:
    return build_packet(CMD_PING)


def frame_read(sn: int) -> bytes:
    return build_packet(CMD_P0_SEND, struct.pack(">I", sn & 0xFFFFFFFF) + bytes([ACTION_READ]))


def frame_write(sn: int, flags: bytes, data: bytes) -> bytes:
    return build_packet(CMD_P0_SEND, struct.pack(">I", sn & 0xFFFFFFFF) + bytes([ACTION_WRITE]) + flags + data)


# --- replies ---------------------------------------------------------------------


def parse_passcode(payload: bytes) -> str:
    """0x0007 -> passcode, '' when the pump is not in binding mode."""
    if len(payload) < 2:
        return ""
    n = struct.unpack(">H", payload[:2])[0]
    return payload[2 : 2 + n].decode("ascii", "replace")


def login_ok(payload: bytes) -> bool:
    return payload[:1] == b"\x00"


def _lv_fields(payload: bytes) -> list[bytes]:
    out, i = [], 0
    while i + 2 <= len(payload):
        n = struct.unpack(">H", payload[i : i + 2])[0]
        i += 2
        out.append(payload[i : i + n])
        i += n
    return out


def parse_discovery(payload: bytes) -> dict | None:
    """0x0004 -> {did, mac, firmware, product_key}."""
    f = _lv_fields(payload)
    if len(f) < 4 or len(f[3]) != 32:
        return None
    try:
        return {
            "did": f[0].decode("ascii"),
            "mac": f[1].hex(":"),
            "firmware": f[2].decode("ascii", "replace"),
            "product_key": f[3].decode("ascii"),
        }
    except UnicodeDecodeError:
        return None


def parse_info(payload: bytes) -> dict:
    """0x0014 -> {module, firmware, product_key}. Fixed 8-byte text fields, product key further in."""
    text = lambda b: b.rstrip(b"\x00 ").decode("ascii", "replace")  # noqa: E731
    pk = ""
    for i in range(0, max(0, len(payload) - 31)):
        chunk = payload[i : i + 32]
        if all(c in b"0123456789abcdef" for c in chunk):
            pk = chunk.decode()
            break
    return {"module": text(payload[0:8]), "firmware": text(payload[8:16]), "product_key": pk}


def status_from_p0(cmd: int, payload: bytes, length: int) -> bytes | None:
    """Status block out of a P0 packet from the device, or None.

    0x0094 carries the 4-byte sequence number before the action byte; 0x0091
    may or may not, so both shapes are tried against the expected length.
    The EcoDrift module (04020B25) pushes changes as 0x0093: sequence 0, then the
    device id as a length-prefixed string, then the report (action 0x04 + status).
    """
    if cmd == CMD_P0_SEND:
        if len(payload) < 6:
            return None
        n = struct.unpack(">H", payload[4:6])[0]
        body = payload[6 + n :]
        if len(body) == 1 + length and body[0] in (ACTION_READ_REPLY, ACTION_REPORT):
            return bytes(body[1:])
        return None
    if cmd not in (CMD_P0_REPORT, CMD_P0_REPLY):
        return None
    for off in (4, 0):
        body = payload[off:]
        if len(body) == 1 + length and body[0] in (ACTION_READ_REPLY, ACTION_REPORT):
            return bytes(body[1:])
    return None


# --- datapoint schemas -------------------------------------------------------------


@dataclass(frozen=True)
class Attr:
    """One datapoint: bit field (unit 'bit') or byte field (unit 'byte')."""

    id: int
    name: str
    kind: str  # 'bool' | 'enum' | 'uint8' | 'binary'
    offset: int
    bit: int = 0
    length: int = 1  # bits for bit fields, bytes otherwise
    unit: str = "byte"
    writable: bool = True


def _bits(base_id: int, spec: list[tuple[str, str, int, int]], offset: int) -> list[Attr]:
    return [
        Attr(base_id + i, name, kind, offset, bit, ln, "bit")
        for i, (name, kind, bit, ln) in enumerate(spec)
    ]


def _bytes(base_id: int, spec: list[tuple[str, str, int, int]]) -> list[Attr]:
    return [Attr(base_id + i, name, kind, off, 0, ln, "byte") for i, (name, kind, off, ln) in enumerate(spec)]


def _slots(base_id: int, offset: int, size: int) -> list[Attr]:
    return [Attr(base_id + i, f"AutoTime{i:02d}", "binary", offset + size * i, 0, size, "byte") for i in range(SLOTS)]


def _faults(base_id: int, offset: int) -> list[Attr]:
    names = (
        "Fault_Overcurrent", "Fault_Overvoltage", "Fault_OverTemp", "Fault_Undervoltage",
        "Fault_Lockedrotor", "Fault_no_liveload", "Fault_UART",
    )
    return [Attr(base_id + i, n, "bool", offset, i, 1, "bit", writable=False) for i, n in enumerate(names)]


FAULT_KEYS = {
    "Fault_Overcurrent": "overcurrent",
    "Fault_Overvoltage": "overvoltage",
    "Fault_OverTemp": "overtemperature",
    "Fault_Undervoltage": "undervoltage",
    "Fault_Lockedrotor": "locked_rotor",
    "Fault_no_liveload": "no_load",
    "Fault_UART": "module_link",
}

# EcoDrift x.3 / SmartDrift ("Current_Pump", packet version 4): 393 bytes status
ECODRIFT_ATTRS: list[Attr] = (
    _bits(0, [
        ("SwitchON", "bool", 0, 1), ("PulseTide", "bool", 1, 1), ("FeedSwitch", "bool", 2, 1),
        ("TimerON", "bool", 3, 1), ("AutoPulseTide", "bool", 4, 1), ("Mode", "enum", 5, 2),
        ("Linkage", "enum", 7, 2), ("AutoMode", "enum", 9, 3),
    ], 0)
    + _bytes(8, [
        ("Flow", "uint8", 2, 1), ("Frequency", "uint8", 3, 1), ("FeedTime", "uint8", 4, 1),
        ("AutoFlow", "uint8", 5, 1), ("AutoFreq", "uint8", 6, 1), ("AutoFeedTime", "uint8", 7, 1),
    ])
    + _slots(14, 8, 8)
    + _faults(62, 392)
)

# DC Runner x.3 ("DC_Runner", packet version 4): 302 bytes status
DC_RUNNER_ATTRS: list[Attr] = (
    _bits(0, [
        ("SwitchON", "bool", 0, 1), ("Mode", "bool", 1, 1), ("FeedSwitch", "bool", 2, 1),
        ("TimerON", "bool", 3, 1), ("AutoMode", "enum", 4, 2),
    ], 0)
    + _bytes(5, [
        ("Motor_Speed", "uint8", 1, 1), ("FeedTime", "uint8", 2, 1), ("AutoGears", "uint8", 3, 1),
        ("AutoFeedTime", "uint8", 4, 1), ("YMDData", "binary", 5, 4), ("HMSData", "binary", 9, 4),
    ])
    + _slots(11, 13, 6)
    + _faults(59, 301)
)


class Schema:
    """Encoder/decoder for one product's status block."""

    def __init__(self, product_key: str, attrs: list[Attr]) -> None:
        self.product_key = product_key
        self.attrs = attrs
        self.by_name = {a.name: a for a in attrs}
        self.length = max(a.offset + self._byte_len(a) for a in attrs)
        writable = [a for a in attrs if a.writable]
        self.write_length = max(a.offset + self._byte_len(a) for a in writable)
        self.flag_bytes = (max(a.id for a in writable) + 8) // 8
        # bit fields sharing an offset form one big-endian word, bit 0 = least significant
        self._groups: dict[int, int] = {}
        for a in attrs:
            if a.unit == "bit":
                self._groups[a.offset] = max(self._groups.get(a.offset, 0), self._byte_len(a))

    @staticmethod
    def _byte_len(a: Attr) -> int:
        return (a.bit + a.length + 7) // 8 if a.unit == "bit" else a.length

    def decode(self, data: bytes) -> dict[str, int | bool | bytes]:
        if len(data) < self.length:
            raise ProtocolError(f"status too short: {len(data)} < {self.length}")
        out: dict[str, int | bool | bytes] = {}
        for a in self.attrs:
            if a.unit == "bit":
                word = int.from_bytes(data[a.offset : a.offset + self._groups[a.offset]], "big")
                v = (word >> a.bit) & ((1 << a.length) - 1)
                out[a.name] = bool(v) if a.kind == "bool" else v
            elif a.kind == "binary":
                out[a.name] = bytes(data[a.offset : a.offset + a.length])
            else:
                out[a.name] = int.from_bytes(data[a.offset : a.offset + a.length], "big")
        return out

    def encode_write(self, values: dict[str, int | bool | bytes], base: bytes | None = None) -> tuple[bytes, bytes]:
        """Flags and data block of a write that changes only ``values``.

        One flag bit per datapoint id (big-endian, like the app). The data block starts
        from ``base`` (the last status) when given, so a firmware that ignored the flags
        would still see the current values everywhere else, and from zeros otherwise.
        """
        data = bytearray(base[: self.write_length] if base else b"")
        data += bytes(self.write_length - len(data))
        flags = 0
        for name, value in values.items():
            a = self.by_name.get(name)
            if a is None or not a.writable:
                raise ProtocolError(f"{name} is not writable")
            flags |= 1 << a.id
            if a.unit == "bit":
                size = self._groups[a.offset]
                word = int.from_bytes(data[a.offset : a.offset + size], "big")
                mask = ((1 << a.length) - 1) << a.bit
                word = (word & ~mask) | ((int(value) << a.bit) & mask)
                data[a.offset : a.offset + size] = word.to_bytes(size, "big")
            elif a.kind == "binary":
                raw = bytes(value)  # type: ignore[arg-type]
                if len(raw) != a.length:
                    raise ProtocolError(f"{name} needs {a.length} bytes")
                data[a.offset : a.offset + a.length] = raw
            else:
                data[a.offset : a.offset + a.length] = int(value).to_bytes(a.length, "big")
        return flags.to_bytes(self.flag_bytes, "big"), bytes(data)


SCHEMAS: dict[str, Schema] = {
    PRODUCT_ECODRIFT: Schema(PRODUCT_ECODRIFT, ECODRIFT_ATTRS),
    PRODUCT_DC_RUNNER: Schema(PRODUCT_DC_RUNNER, DC_RUNNER_ATTRS),
}


def schema_for(product_key: str) -> Schema | None:
    return SCHEMAS.get(product_key)


# --- friendly values ----------------------------------------------------------------

WAVE_MODES = ("classic", "sine", "random", "constant")  # EcoDrift Mode 0..3
AUTO_MODES = ("off", "classic", "sine", "random", "constant", "feed")  # EcoDrift AutoMode 0..5
LINKAGE = ("independent", "master", "slave")
WAVE_FORMS = ("pulse", "tide")  # PulseTide 0/1
DC_AUTO_MODES = ("off", "auto", "feed")  # DC Runner AutoMode 0..2
DC_CONTROL = ("ap", "wireless")  # DC Runner Mode 0/1


def _enum(names: tuple[str, ...], v: int) -> str | int:
    return names[v] if 0 <= v < len(names) else v


def _hhmm(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}"


def _ecodrift_slot(raw: bytes) -> dict | None:
    if len(raw) != 8 or raw[0] == SLOT_EMPTY:
        return None
    return {
        "start": _hhmm(raw[0], raw[1]),
        "end": _hhmm(raw[2], raw[3]),
        "mode": _enum(AUTO_MODES, raw[4]),
        "flow": raw[5],  # feed time in minutes when mode == feed
        "frequency": raw[6],
        "wave_form": _enum(WAVE_FORMS, raw[7]),
    }


def _dc_slot(raw: bytes) -> dict | None:
    if len(raw) != 6 or raw[0] == SLOT_EMPTY:
        return None
    return {
        "start": _hhmm(raw[0], raw[1]),
        "end": _hhmm(raw[2], raw[3]),
        "mode": _enum(DC_AUTO_MODES, raw[4]),
        "speed": raw[5],  # feed time in minutes when mode == feed
    }


def _faults_out(raw: dict, out: dict) -> None:
    faults = {FAULT_KEYS[k]: bool(raw[k]) for k in FAULT_KEYS if k in raw}
    out["faults"] = faults
    out["fault_active"] = any(faults.values())
    out["fault_list"] = [k for k, v in faults.items() if v]


def decode_status(product_key: str, data: bytes) -> dict | None:
    """Status block -> friendly dict (keys documented in the README), None for unknown products."""
    schema = schema_for(product_key)
    if schema is None:
        return None
    raw = schema.decode(data)
    out: dict = {}
    if product_key == PRODUCT_ECODRIFT:
        out.update({
            "power": raw["SwitchON"],
            "wave_form": _enum(WAVE_FORMS, int(raw["PulseTide"])),
            "feed": raw["FeedSwitch"],
            "timer": raw["TimerON"],
            "auto_wave_form": _enum(WAVE_FORMS, int(raw["AutoPulseTide"])),
            "mode": _enum(WAVE_MODES, raw["Mode"]),
            "linkage": _enum(LINKAGE, raw["Linkage"]),
            "auto_mode": _enum(AUTO_MODES, raw["AutoMode"]),
            "flow": raw["Flow"],
            "frequency": raw["Frequency"],
            "feed_time": raw["FeedTime"],
            "auto_flow": raw["AutoFlow"],
            "auto_frequency": raw["AutoFreq"],
            "auto_feed_time": raw["AutoFeedTime"],
        })
        slots = [_ecodrift_slot(raw[f"AutoTime{i:02d}"]) for i in range(SLOTS)]
    else:
        out.update({
            "power": raw["SwitchON"],
            "control": _enum(DC_CONTROL, int(raw["Mode"])),
            "feed": raw["FeedSwitch"],
            "timer": raw["TimerON"],
            "auto_mode": _enum(DC_AUTO_MODES, raw["AutoMode"]),
            "speed": raw["Motor_Speed"],
            "feed_time": raw["FeedTime"],
            "auto_speed": raw["AutoGears"],
            "auto_feed_time": raw["AutoFeedTime"],
        })
        ymd, hms = raw["YMDData"], raw["HMSData"]
        if any(ymd):
            out["device_date"] = f"{ymd[0] * 100 + ymd[1]:04d}-{ymd[2]:02d}-{ymd[3]:02d}"
        out["device_time"] = f"{hms[1]:02d}:{hms[2]:02d}:{hms[3]:02d}"
        slots = [_dc_slot(raw[f"AutoTime{i:02d}"]) for i in range(SLOTS)]
    out["schedule"] = [dict(slot=i, **s) for i, s in enumerate(slots) if s]
    _faults_out(raw, out)
    return out


# --- writes (friendly name -> datapoint) ------------------------------------------------

_ECODRIFT_WRITE = {
    "power": ("SwitchON", None),
    "wave_form": ("PulseTide", WAVE_FORMS),
    "feed": ("FeedSwitch", None),
    "timer": ("TimerON", None),
    "mode": ("Mode", WAVE_MODES),
    "linkage": ("Linkage", LINKAGE),
    "flow": ("Flow", (0, 100)),
    "frequency": ("Frequency", (0, 100)),
    "feed_time": ("FeedTime", (1, 60)),
}
_DC_WRITE = {
    "power": ("SwitchON", None),
    "feed": ("FeedSwitch", None),
    "timer": ("TimerON", None),
    "speed": ("Motor_Speed", (0, 100)),
    "feed_time": ("FeedTime", (1, 60)),
}
WRITE_MAP = {PRODUCT_ECODRIFT: _ECODRIFT_WRITE, PRODUCT_DC_RUNNER: _DC_WRITE}


# EcoDrift firmware 04020B25 ignores a write whose only flag is Flow (tested 05.11.2026);
# Flow together with any second flag is applied. So a flow write always carries the
# frequency as well, with its current value - the app sends both from the same screen.
_COMPANION = {PRODUCT_ECODRIFT: {"flow": ("frequency", "Frequency")}}


def encode_values(product_key: str, values: dict, base: bytes | None = None) -> tuple[bytes, bytes]:
    """Friendly values ({'flow': 60, 'mode': 'random'}) -> (flags, data) for frame_write()."""
    schema = schema_for(product_key)
    table = WRITE_MAP.get(product_key)
    if schema is None or table is None:
        raise ProtocolError(f"unknown product {product_key}")
    values = dict(values)
    for key, (companion, attr) in _COMPANION.get(product_key, {}).items():
        if key in values and companion not in values:
            if base is None:
                raise ProtocolError(f"{key} needs the current status (companion {companion})")
            values[companion] = schema.decode(base)[attr]
    raw: dict[str, int | bool | bytes] = {}
    for key, value in values.items():
        if key not in table:
            raise ProtocolError(f"{key} cannot be written")
        name, spec = table[key]
        if spec is None:
            raw[name] = 1 if value else 0
        elif isinstance(spec, tuple) and spec and isinstance(spec[0], str):
            if value not in spec:
                raise ProtocolError(f"{key}: {value!r} not in {spec}")
            raw[name] = spec.index(value)
        else:
            lo, hi = spec  # type: ignore[misc]
            v = int(round(float(value)))
            if not lo <= v <= hi:
                raise ProtocolError(f"{key}: {v} outside {lo}..{hi}")
            raw[name] = v
    return schema.encode_write(raw, base)
