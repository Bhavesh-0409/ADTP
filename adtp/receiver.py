"""Reliable one-way UDP receiver for build-plan steps 2--3."""

from __future__ import annotations

import asyncio
import hashlib
import socket
from pathlib import Path
from typing import Optional

from . import config
from .connection import ConnState
from .metrics import RunLog
from .packet import ChecksumError, Packet, PacketError, PacketType, now_us


class _ReceiverEndpoint(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[Packet, tuple[str, int]]] = asyncio.Queue()
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            self.queue.put_nowait((Packet.decode(data), addr))
        except (PacketError, ChecksumError):
            pass


class Receiver:
    def __init__(self, local: tuple[str, int], out_path: str, log: RunLog,
                 transfer_timeout: float = 30.0) -> None:
        self.local, self.out_path, self.log = local, Path(out_path), log
        self.transfer_timeout = transfer_timeout
        self.state = ConnState.CLOSED
        self.expected = 1
        self.buffer: dict[int, bytes] = {}
        self.peer: Optional[tuple[str, int]] = None

    async def receive_file(self) -> dict:
        endpoint = _ReceiverEndpoint()
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: endpoint, local_addr=self.local, family=socket.AF_INET)
        self.state = ConnState.LISTEN
        written = bytearray()
        try:
            while True:
                packet, addr = await asyncio.wait_for(endpoint.queue.get(), self.transfer_timeout)
                if self.peer is not None and addr != self.peer:
                    continue
                if packet.type is PacketType.SYN:
                    self.peer = addr
                    self.state = ConnState.SYN_RCVD
                    self._send(endpoint, Packet(PacketType.SYN_ACK, seq=0, ack=packet.seq + 1,
                                                window=self._free_window(), ts=now_us(), ts_echo=packet.ts))
                elif packet.type is PacketType.ACK and self.state is ConnState.SYN_RCVD:
                    self.state = ConnState.ESTABLISHED
                elif packet.type is PacketType.DATA and self.state in (ConnState.SYN_RCVD, ConnState.ESTABLISHED):
                    # The final handshake ACK may be lost.  DATA from the same peer proves
                    # the sender received SYN_ACK, so complete the handshake and deliver it.
                    self.state = ConnState.ESTABLISHED
                    self._data(endpoint, packet, written)
                elif packet.type is PacketType.FIN and self.state is ConnState.ESTABLISHED:
                    self._send(endpoint, Packet(PacketType.ACK, ack=packet.seq + 1,
                                                window=self._free_window(), ts=now_us(), ts_echo=packet.ts))
                    self.out_path.parent.mkdir(parents=True, exist_ok=True)
                    self.out_path.write_bytes(written)
                    self.state = ConnState.CLOSED
                    return {"bytes": len(written), "sha256": hashlib.sha256(written).hexdigest()}
        finally:
            transport.close()

    def _free_window(self) -> int:
        return max(0, config.RECV_WINDOW - len(self.buffer))

    def _send(self, endpoint: _ReceiverEndpoint, packet: Packet) -> None:
        assert endpoint.transport is not None and self.peer is not None
        endpoint.transport.sendto(packet.encode(), self.peer)

    def _data(self, endpoint: _ReceiverEndpoint, packet: Packet, written: bytearray) -> None:
        if packet.seq == self.expected:
            written.extend(packet.payload)
            self.expected += 1
            while self.expected in self.buffer:
                written.extend(self.buffer.pop(self.expected))
                self.expected += 1
        elif self.expected < packet.seq < self.expected + config.RECV_WINDOW:
            self.buffer.setdefault(packet.seq, packet.payload)
        # Cumulative ACK(expected) also makes a gap visible as duplicate ACKs.
        self._send(endpoint, Packet(PacketType.ACK, ack=self.expected, window=self._free_window(),
                                    ts=now_us(), ts_echo=packet.ts))
