"""Persistent LAN connection to one Aqua Medic (Gizwits) pump.

The pump keeps the TCP session open, answers a heartbeat every few seconds and
pushes a full status block whenever something changes (app, buttons, timer).
Several clients may be logged in at the same time, so the app keeps working.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import socket
import time

from . import protocol as pr

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 8
PING_SECONDS = 4
PONG_TIMEOUT = 20  # no answer for this long -> reconnect
RECONNECT_MIN = 5
RECONNECT_MAX = 60
STALE_SECONDS = 90


class PumpError(Exception):
    """Login or protocol problem."""


class NeedsBinding(PumpError):
    """The pump did not hand out its passcode (not in binding mode) and none is stored."""


async def _request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, buf: pr.PacketBuffer,
                   frame: bytes, expect: int, timeout: float = CONNECT_TIMEOUT) -> bytes:
    writer.write(frame)
    await writer.drain()
    async with asyncio.timeout(timeout):
        while True:
            data = await reader.read(4096)
            if not data:
                raise PumpError("connection closed")
            for cmd, payload in buf.feed(data):
                if cmd == expect:
                    return payload


async def async_probe(host: str, passcode: str | None = None, timeout: float = CONNECT_TIMEOUT) -> dict:
    """Connect once: fetch the passcode (if needed), log in, read module info and one status.

    Returns {passcode, module, firmware, product_key, status}. Raises NeedsBinding / PumpError / OSError.
    """
    async with asyncio.timeout(timeout):
        reader, writer = await asyncio.open_connection(host, pr.TCP_PORT)
    buf = pr.PacketBuffer()
    try:
        offered = pr.parse_passcode(await _request(reader, writer, buf, pr.frame_passcode_request(), pr.CMD_PASSCODE_RESP))
        pc = offered or passcode
        if not pc:
            raise NeedsBinding("pump is not in binding mode")
        if not pr.login_ok(await _request(reader, writer, buf, pr.frame_login(pc), pr.CMD_LOGIN_RESP)):
            raise PumpError("login refused")
        info = pr.parse_info(await _request(reader, writer, buf, pr.frame_info_request(), pr.CMD_INFO_RESP))
        schema = pr.schema_for(info["product_key"])
        status = None
        if schema is not None:
            writer.write(pr.frame_read(1))
            await writer.drain()
            async with asyncio.timeout(timeout):
                while status is None:
                    data = await reader.read(4096)
                    if not data:
                        raise PumpError("connection closed")
                    for cmd, payload in buf.feed(data):
                        status = pr.status_from_p0(cmd, payload, schema.length)
                        if status is not None:
                            break
        return {"passcode": pc, "status": status, **info}
    finally:
        writer.close()


async def async_discover(timeout: float = 3.0, target: str = "255.255.255.255") -> list[dict]:
    """UDP broadcast, as the app does. Returns [{host, did, mac, firmware, product_key}]."""
    loop = asyncio.get_running_loop()
    found: dict[str, dict] = {}

    class Listener(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple) -> None:
            try:
                cmd, payload = pr.parse_packet(data)
            except (pr.ProtocolError, IndexError):
                return
            if cmd == pr.CMD_DISCOVER_REPLY and (info := pr.parse_discovery(payload)):
                found[addr[0]] = {"host": addr[0], **info}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)
    sock.bind(("", 0))
    transport, _ = await loop.create_datagram_endpoint(Listener, sock=sock)
    try:
        transport.sendto(pr.frame_discover(), (target, pr.UDP_PORT))
        await asyncio.sleep(timeout)
    finally:
        transport.close()
    return list(found.values())


class PumpClient:
    """Keeps the session alive and pushes decoded status to the coordinator."""

    def __init__(
        self,
        host: str,
        product_key: str,
        passcode: str,
        on_data: Callable[[dict], None],
        on_connection: Callable[[bool], None],
        on_info: Callable[[dict], None] | None = None,
    ) -> None:
        self.host = host
        self.product_key = product_key
        self.passcode = passcode
        self.schema = pr.schema_for(product_key)
        self._on_data = on_data
        self._on_connection = on_connection
        self._on_info = on_info
        self.connected = False
        self.last_data = 0.0
        self.last_status: bytes | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._sn = 1
        self._stop = asyncio.Event()
        self._last_rx = 0.0

    async def run(self) -> None:
        if self.schema is None:
            _LOGGER.error("%s: unknown product %s", self.host, self.product_key)
            return
        delay = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                await self._session()
                delay = RECONNECT_MIN
            except asyncio.CancelledError:
                raise
            except (OSError, PumpError, asyncio.TimeoutError, pr.ProtocolError) as err:
                if self._stop.is_set():
                    pass
                elif self.connected:
                    _LOGGER.warning("%s: connection lost (%s)", self.host, err)
                else:
                    _LOGGER.debug("%s: connect failed (%s)", self.host, err)
            finally:
                self._set_connected(False)
            if self._stop.is_set():
                break
            try:
                async with asyncio.timeout(delay):
                    await self._stop.wait()
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, RECONNECT_MAX)

    async def stop(self) -> None:
        self._stop.set()
        if self._writer is not None:
            self._writer.close()

    def _set_connected(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            self._on_connection(value)

    async def _session(self) -> None:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            reader, writer = await asyncio.open_connection(self.host, pr.TCP_PORT)
        self._writer = writer
        buf = pr.PacketBuffer()
        try:
            offered = pr.parse_passcode(await _request(reader, writer, buf, pr.frame_passcode_request(), pr.CMD_PASSCODE_RESP))
            if offered and offered != self.passcode:
                _LOGGER.info("%s: pump offers a new passcode, using it", self.host)
                self.passcode = offered
            if not pr.login_ok(await _request(reader, writer, buf, pr.frame_login(self.passcode), pr.CMD_LOGIN_RESP)):
                raise PumpError("login refused")
            info = pr.parse_info(await _request(reader, writer, buf, pr.frame_info_request(), pr.CMD_INFO_RESP))
            if self._on_info:
                self._on_info(info)
            self._set_connected(True)
            self._last_rx = time.monotonic()
            writer.write(pr.frame_read(self._next_sn()))
            await writer.drain()
            ping = asyncio.ensure_future(self._heartbeat(writer))
            try:
                while True:
                    async with asyncio.timeout(PONG_TIMEOUT):
                        data = await reader.read(4096)
                    if not data:
                        raise PumpError("connection closed by pump")
                    self._last_rx = time.monotonic()
                    for cmd, payload in buf.feed(data):
                        self._handle(cmd, payload)
            finally:
                ping.cancel()
        finally:
            self._writer = None
            writer.close()

    async def _heartbeat(self, writer: asyncio.StreamWriter) -> None:
        while True:
            await asyncio.sleep(PING_SECONDS)
            if time.monotonic() - self._last_rx > PONG_TIMEOUT:
                writer.close()  # the reader notices and reconnects
                return
            writer.write(pr.frame_ping())
            try:
                await writer.drain()
            except OSError:
                return

    def _next_sn(self) -> int:
        self._sn = (self._sn % 0xFFFFFFFE) + 1
        return self._sn

    def _handle(self, cmd: int, payload: bytes) -> None:
        if cmd == pr.CMD_PONG:
            return
        status = pr.status_from_p0(cmd, payload, self.schema.length) if self.schema else None
        if status is None:
            if cmd in (pr.CMD_P0_REPLY, pr.CMD_P0_REPORT, pr.CMD_P0_SEND) and len(payload) != 4:  # 4 bytes = write ack
                _LOGGER.debug("%s: P0 cmd 0x%04x without status, %d bytes: %s", self.host, cmd, len(payload), payload[:16].hex())
            return
        self.last_status = status
        self.last_data = time.monotonic()
        data = pr.decode_status(self.product_key, status)
        if data is not None:
            _LOGGER.debug("%s: status via 0x%04x: %s", self.host, cmd, {k: v for k, v in data.items() if k not in ("schedule", "faults")})
            self._on_data(data)

    async def async_write(self, values: dict) -> None:
        """Change the given friendly values ({'flow': 60}); the pump answers with a status push."""
        if self._writer is None or not self.connected:
            raise ConnectionError("pump not connected")
        flags, data = pr.encode_values(self.product_key, values, self.last_status)
        _LOGGER.debug("%s: write %s flags=%s", self.host, values, flags.hex())
        self._writer.write(pr.frame_write(self._next_sn(), flags, data))
        await self._writer.drain()
        # ask for the full status right after, in case the pump only acknowledges
        self._writer.write(pr.frame_read(self._next_sn()))
        await self._writer.drain()
