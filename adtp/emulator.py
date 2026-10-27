"""UDP network emulator: propagation delay, loss, bandwidth and drop-tail queue.

Virtual-time bottleneck model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Instead of sleeping per packet (which on Windows rounds up to ~15.6 ms,
destroying throughput on fast links), we track when the link becomes free
after serialising the current packet:

    next_free = max(now, next_free) + packet_bits / bandwidth

Delivery is scheduled at ``next_free + propagation_delay`` via
``loop.call_later``, so hundreds of packets can be "in the wire"
concurrently without any blocking sleeps.

Queue occupancy is tracked with a simple counter: incremented on
admission, decremented via ``call_later`` when the packet's
serialisation finishes (its virtual departure time).  This makes
drop-tail decisions deterministic — no wall-clock races between
successive ``datagram_received`` calls.

ACKs (receiver -> sender) get propagation delay only (no bandwidth /
queue limit), matching a typical asymmetric model where the return path
is not the bottleneck.

Why perf_counter and not monotonic?
  Both are monotonic on all platforms, but perf_counter has higher
  resolution on Windows (~100 ns vs ~15 ms for time.time).  We only
  need *relative* timestamps so epoch doesn't matter.
"""

from __future__ import annotations

import random
import socket
import time
from typing import Optional

import asyncio

from .metrics import RunLog
from .packet import Packet, PacketError
from .scenarios import Conditions


class Emulator(asyncio.DatagramProtocol):
    """Transparent UDP proxy; the sender-to-receiver direction has the bottleneck."""

    def __init__(self, listen: tuple[str, int], target: tuple[str, int],
                 conditions: Conditions, log: RunLog, seed: int = 42) -> None:
        self.listen, self.target, self.conditions, self.log = listen, target, conditions, log
        self.rng = random.Random(seed)
        self.sender: Optional[tuple[str, int]] = None
        self.transport: Optional[asyncio.DatagramTransport] = None

        # Virtual-time state for the sender->receiver bottleneck link.
        # _next_free is the perf_counter timestamp when the link finishes
        # serialising the last admitted packet.  Starts at 0 (past).
        self._next_free: float = 0.0
        # Simple counter: packets admitted but not yet serialised.
        # Incremented on admission, decremented by a call_later callback
        # at the packet's virtual departure time.  Deterministic for bursts
        # because call_later callbacks cannot fire between synchronous
        # datagram_received calls.
        self._queue_size: int = 0

    async def start(self) -> None:
        if self.transport is None:
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: self, local_addr=self.listen, family=socket.AF_INET)
            self.transport = transport

    async def stop(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def set_conditions(self, **changes) -> None:
        for key, value in changes.items():
            if not hasattr(self.conditions, key):
                raise ValueError(f"unknown network condition '{key}'")
            setattr(self.conditions, key, value)

    # ------------------------------------------------------------------
    # Packet arrival
    # ------------------------------------------------------------------

    def datagram_received(self, raw: bytes, addr: tuple[str, int]) -> None:
        try:
            packet = Packet.decode(raw)
        except PacketError:
            return

        if addr == self.target:
            # ACK / control coming back from the receiver.
            # Only propagation delay, no bandwidth limit on the return path.
            if self.sender is not None:
                self._schedule_delivery(raw, packet, self.sender,
                                        "receiver_to_sender")
            return

        # Sender -> receiver direction: apply loss, queue, bandwidth.
        self.sender = addr

        # 1. Random loss (decided before the queue, so the label is clean).
        if self.rng.random() < self.conditions.loss_pct / 100:
            self._drop(packet, "random")
            return

        # 2. Queue admission: counter-based, deterministic for bursts.
        if self._queue_size >= self.conditions.queue_pkts:
            self._drop(packet, "queue_overflow")
            return

        # 3. Compute serialisation / departure time.
        now = time.perf_counter()
        # Use virtual serialisation time for an admitted burst. Looking only
        # at max(now, _next_free) lets Python loop overhead stretch fast-link
        # bursts and makes bandwidth ratios depend on host speed.
        start = self._next_free if self._queue_size else now

        if self.conditions.bandwidth_kbps > 0:
            # Serialisation delay = packet_bits / link_rate.
            serialisation_s = len(raw) * 8 / (self.conditions.bandwidth_kbps * 1000)
        else:
            serialisation_s = 0.0

        departure = start + serialisation_s
        self._next_free = departure

        # Increment queue counter; schedule decrement at departure.
        self._queue_size += 1
        self.log.add("queue", depth=self._queue_size)
        depart_delay = max(0.0, departure - now)

        loop = asyncio.get_running_loop()
        loop.call_later(depart_delay, self._on_depart)

        # 4. Schedule forwarding at departure + propagation delay.
        propagation_s = max(0.0, self.conditions.delay_ms) / 1000
        delivery_delay = max(0.0, departure + propagation_s - now)
        loop.call_later(delivery_delay, self._deliver, raw, packet,
                        self.target, "sender_to_receiver")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_depart(self) -> None:
        """A packet finished serialisation — one slot freed in the queue."""
        self._queue_size = max(0, self._queue_size - 1)

    def _schedule_delivery(self, raw: bytes, packet: Packet,
                           destination: tuple[str, int], direction: str) -> None:
        """Schedule a packet for delivery after propagation delay only."""
        propagation_s = max(0.0, self.conditions.delay_ms) / 1000
        loop = asyncio.get_running_loop()
        loop.call_later(propagation_s, self._deliver, raw, packet,
                        destination, direction)

    def _deliver(self, raw: bytes, packet: Packet,
                 destination: tuple[str, int], direction: str) -> None:
        """Actually send the packet to its destination (called by the event loop)."""
        if self.transport is not None:
            self.transport.sendto(raw, destination)
            self.log.add("forward", seq=packet.seq, ack=packet.ack,
                         type=packet.type.name, direction=direction)

    def _drop(self, packet: Packet, label: str) -> None:
        self.log.add("drop", seq=packet.seq, label=label, where="sender_to_receiver")
