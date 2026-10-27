"""Reliable one-way UDP sender used by build-plan steps 2--4.

Sequence numbers count packets. The sender uses one timer for its oldest
outstanding packet, like classic TCP.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config
from .congestion import CongestionController
from .connection import ConnState
from .metrics import RunLog, summarize
from .packet import ChecksumError, Packet, PacketError, PacketType, now_us
from .rtt import RttEstimator


class _Endpoint(asyncio.DatagramProtocol):
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


@dataclass
class _Inflight:
    payload: bytes
    sent_ts: int
    retransmitted: bool = False


class Sender:
    """Connect to *remote* and send one file, returning headline transfer metrics."""

    def __init__(self, controller: CongestionController, remote: tuple[str, int],
                 log: RunLog, local: tuple[str, int] = ("127.0.0.1", 0),
                 transfer_timeout: float = 30.0) -> None:
        self.controller, self.remote, self.local, self.log = controller, remote, local, log
        self.transfer_timeout = transfer_timeout
        self.rtt = RttEstimator()
        self.peer_window = config.RECV_WINDOW
        self.state = ConnState.CLOSED
        self.base = self.next_seq = 1
        self.inflight: dict[int, _Inflight] = {}
        self.dup_acks = 0
        self._endpoint: Optional[_Endpoint] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._rtt_samples: list[float] = []
        self._packets_sent = self._retransmissions = 0

    async def send_file(self, path: str) -> dict:
        data = Path(path).read_bytes()
        endpoint = _Endpoint()
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: endpoint, local_addr=self.local, family=socket.AF_INET)
        self._endpoint, self._transport = endpoint, transport
        started = time.monotonic()
        try:
            await asyncio.wait_for(self._transfer(data), timeout=self.transfer_timeout)
            result = summarize(time.monotonic() - started, len(data), self._rtt_samples,
                               self._retransmissions, self._packets_sent)
            self.log.summary.update(result)
            return result
        finally:
            transport.close()
            self._transport = None

    async def _transfer(self, data: bytes) -> None:
        await self._handshake()
        chunks = [data[i:i + config.MSS] for i in range(0, len(data), config.MSS)]
        self.log.add("cwnd", **self.controller.snapshot())
        while self.base <= len(chunks):
            self._fill_window(chunks)
            await self._wait_for_ack()
        await self._finish()

    def _send(self, packet: Packet, *, retransmit: bool = False) -> None:
        assert self._transport is not None
        self._transport.sendto(packet.encode(), self.remote)
        if packet.type is PacketType.DATA:
            self._packets_sent += 1
            self._retransmissions += int(retransmit)
            self.log.add("send", seq=packet.seq, retransmit=retransmit)

    async def _recv(self, timeout: float) -> Packet:
        assert self._endpoint is not None
        while True:
            packet, addr = await asyncio.wait_for(self._endpoint.queue.get(), timeout=timeout)
            if addr == self.remote:
                return packet

    async def _handshake(self) -> None:
        self.state = ConnState.SYN_SENT
        for _ in range(8):
            self._send(Packet(PacketType.SYN, seq=0, ts=now_us()))
            deadline = asyncio.get_running_loop().time() + self.rtt.rto
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self.rtt.backoff()
                    break
                try:
                    packet = await self._recv(remaining)
                except asyncio.TimeoutError:
                    self.rtt.backoff()
                    break
                if packet.type is PacketType.SYN_ACK and packet.ack == 1:
                    self.peer_window = packet.window
                    self._send(Packet(PacketType.ACK, seq=1, ack=1, window=config.RECV_WINDOW,
                                      ts=now_us(), ts_echo=packet.ts))
                    self.state = ConnState.ESTABLISHED
                    return
        raise TimeoutError("SYN handshake failed")

    def _fill_window(self, chunks: list[bytes]) -> None:
        limit = min(self.controller.window, self.peer_window)
        while self.next_seq <= len(chunks) and self.next_seq - self.base < limit:
            ts = now_us()
            self.inflight[self.next_seq] = _Inflight(chunks[self.next_seq - 1], ts)
            self._send(Packet(PacketType.DATA, seq=self.next_seq, ts=ts,
                              payload=chunks[self.next_seq - 1]))
            self.next_seq += 1

    async def _wait_for_ack(self) -> None:
        if not self.inflight:
            return
        oldest = self.inflight[self.base]
        elapsed = max(0.0, (now_us() - oldest.sent_ts) / 1_000_000)
        try:
            packet = await self._recv(max(0.001, self.rtt.rto - elapsed))
        except asyncio.TimeoutError:
            self._on_timeout()
            return
        if packet.type is PacketType.ACK:
            self._on_ack(packet)

    def _on_ack(self, packet: Packet) -> None:
        self.peer_window = packet.window
        self.log.add("ack", ack=packet.ack)
        if packet.ack > self.base:
            newly_acked = min(packet.ack, self.next_seq) - self.base
            sample_entry = next((entry for entry in self.inflight.values()
                                 if entry.sent_ts == packet.ts_echo), None)
            if sample_entry is not None and not sample_entry.retransmitted:
                sample = (now_us() - packet.ts_echo) / 1_000_000
                if sample > 0:
                    self.rtt.update(sample)
                    self._rtt_samples.append(sample)
                    self.log.add("rtt", rtt=sample, srtt=self.rtt.srtt, rto=self.rtt.rto,
                                 base_rtt=self.rtt.base_rtt)
            for seq in [n for n in self.inflight if n < packet.ack]:
                del self.inflight[seq]
            self.base = packet.ack
            self.dup_acks = 0
            self.controller.on_ack(newly_acked, self.rtt.recent_rtt, self.rtt.base_rtt)
            self.log.add("cwnd", **self.controller.snapshot())
        elif packet.ack == self.base:
            self.dup_acks += 1
            if self.dup_acks == config.DUP_ACK_THRESHOLD:
                self._loss(self.controller.on_triple_dup_ack(self.rtt.recent_rtt, self.rtt.base_rtt))
                self._retransmit_base()
            elif self.dup_acks > config.DUP_ACK_THRESHOLD:
                self.controller.on_dup_ack()
                self.log.add("cwnd", **self.controller.snapshot())

    def _loss(self, decision) -> None:
        self.log.add("loss", seq=self.base, trigger=decision.trigger,
                     classification=decision.classification, backlog=decision.backlog,
                     cwnd_before=decision.cwnd_before, cwnd_after=decision.cwnd_after,
                     rtt=self.rtt.recent_rtt, base_rtt=self.rtt.base_rtt,
                     reason=decision.reason)
        self.log.add("cwnd", **self.controller.snapshot())

    def _retransmit_base(self) -> None:
        entry = self.inflight[self.base]
        entry.retransmitted = True
        entry.sent_ts = now_us()
        self._send(Packet(PacketType.DATA, seq=self.base, ts=entry.sent_ts, payload=entry.payload),
                   retransmit=True)

    def _on_timeout(self) -> None:
        self._loss(self.controller.on_timeout(self.rtt.recent_rtt, self.rtt.base_rtt))
        self.rtt.backoff()
        self.dup_acks = 0
        self._retransmit_base()

    async def _finish(self) -> None:
        self.state = ConnState.FIN_WAIT
        while self._endpoint is not None and not self._endpoint.queue.empty():
            try:
                self._endpoint.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for _ in range(8):
            self._send(Packet(PacketType.FIN, seq=self.next_seq, ts=now_us()))
            deadline = asyncio.get_running_loop().time() + self.rtt.rto
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self.rtt.backoff()
                    break
                try:
                    packet = await self._recv(remaining)
                except asyncio.TimeoutError:
                    self.rtt.backoff()
                    break
                if packet.type is PacketType.ACK and packet.ack == self.next_seq + 1:
                    self.state = ConnState.CLOSED
                    return
        raise TimeoutError("FIN teardown failed")
