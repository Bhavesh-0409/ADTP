"""Unit tests for the virtual-time emulator bottleneck model.

The first four tests mirror the originals (drop labelling, queue overflow,
seeded loss percentage, boundary values).  They now run inside an asyncio
event loop because the emulator uses ``loop.call_later`` internally.

The last two tests verify that the bottleneck actually models bandwidth
correctly by checking the virtual-time schedule (_next_free) rather than
wall-clock delivery timestamps.  Wall-clock delivery depends on the OS
timer resolution (~15.6 ms on Windows), but the virtual model is exact.
"""

import asyncio
import time

import pytest

from adtp.emulator import Emulator
from adtp.metrics import RunLog
from adtp.packet import Packet, PacketType, HEADER_SIZE
from adtp.scenarios import Conditions


def _data(seq=1):
    return Packet(PacketType.DATA, seq=seq, payload=b"x").encode()


# ---------------------------------------------------------------------------
# Original tests, adapted to run inside an event loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emulator_seeded_random_drop_is_labelled():
    log = RunLog()
    em = Emulator(("127.0.0.1", 9000), ("127.0.0.1", 9001),
                  Conditions(loss_pct=100, queue_pkts=2), log, seed=7)
    em.datagram_received(_data(), ("127.0.0.1", 5000))
    drop = log.of_kind("drop")[0]
    assert drop["seq"] == 1 and drop["label"] == "random" and drop["where"] == "sender_to_receiver"


@pytest.mark.asyncio
async def test_emulator_queue_overflow_and_live_conditions():
    log = RunLog()
    em = Emulator(("127.0.0.1", 9000), ("127.0.0.1", 9001),
                  Conditions(loss_pct=0, queue_pkts=1, bandwidth_kbps=8000), log, seed=1)
    em.datagram_received(_data(1), ("127.0.0.1", 5000))
    em.datagram_received(_data(2), ("127.0.0.1", 5000))
    # Counter-based queue: first packet increments to 1, second sees 1 >= 1, drops.
    # No wall-clock race because call_later can't fire between synchronous calls.
    assert log.of_kind("queue")[0]["depth"] == 1
    assert log.of_kind("drop")[0]["seq"] == 2
    assert log.of_kind("drop")[0]["label"] == "queue_overflow"
    em.set_conditions(loss_pct=5, delay_ms=12)
    assert em.conditions.loss_pct == 5 and em.conditions.delay_ms == 12


@pytest.mark.asyncio
async def test_emulator_loss_percent_uses_seeded_percent_units():
    """3 means 3%, not a probability of 3.0 (which would drop every packet)."""
    log = RunLog()
    em = Emulator(("127.0.0.1", 9000), ("127.0.0.1", 9001),
                  Conditions(loss_pct=3, queue_pkts=20_000, bandwidth_kbps=0), log, seed=42)
    for seq in range(1, 10_001):
        em.datagram_received(_data(seq), ("127.0.0.1", 5000))
    drops = len(log.of_kind("drop"))
    assert 250 <= drops <= 350  # deterministic sample: close to the requested 3%


@pytest.mark.asyncio
async def test_emulator_zero_and_full_random_loss_boundaries():
    for loss_pct, expected in ((0, 0), (100, 100)):
        log = RunLog()
        em = Emulator(("127.0.0.1", 9000), ("127.0.0.1", 9001),
                      Conditions(loss_pct=loss_pct, queue_pkts=200, bandwidth_kbps=0), log, seed=9)
        for seq in range(1, 101):
            em.datagram_received(_data(seq), ("127.0.0.1", 5000))
        assert len(log.of_kind("drop")) == expected


# ---------------------------------------------------------------------------
# NEW: Bottleneck bandwidth model tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bottleneck_virtual_time_matches_expected_serialisation():
    """Feed 1000 packets at 8000 kbps and verify that the virtual-time
    schedule (_next_free) advances by exactly n * packet_bits / bandwidth.

    This tests the bandwidth model directly without depending on OS timer
    resolution.  Separately verifies that all packets are eventually
    forwarded via a real UDP socket.
    """
    import socket as sock_mod

    n_packets = 1000
    bandwidth_kbps = 8000
    raw = _data(1)
    packet_bits = len(raw) * 8
    expected_ser_total = n_packets * packet_bits / (bandwidth_kbps * 1000)

    # --- Part 1: verify the virtual-time model (no real socket needed) ---
    log = RunLog()
    em = Emulator(("127.0.0.1", 9000), ("127.0.0.1", 9001),
                  Conditions(delay_ms=0, loss_pct=0, bandwidth_kbps=bandwidth_kbps,
                             queue_pkts=n_packets + 10), log, seed=1)
    fake_sender = ("127.0.0.1", 55555)
    t_before = time.perf_counter()
    for seq in range(1, n_packets + 1):
        em.datagram_received(_data(seq), fake_sender)
    t_after = time.perf_counter()

    # _next_free should have advanced by ~ expected_ser_total from the first
    # packet's arrival time.  Allow for Python loop overhead.
    virtual_span = em._next_free - t_before
    assert virtual_span == pytest.approx(expected_ser_total, rel=0.15), (
        f"Virtual span {virtual_span:.6f}s vs expected {expected_ser_total:.6f}s"
    )

    # --- Part 2: verify all packets are actually forwarded ---
    sink = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_DGRAM)
    sink.bind(("127.0.0.1", 0))
    sink.setblocking(False)
    sink_addr = sink.getsockname()
    log2 = RunLog()
    em2 = Emulator(("127.0.0.1", 0), sink_addr,
                   Conditions(delay_ms=0, loss_pct=0, bandwidth_kbps=bandwidth_kbps,
                              queue_pkts=n_packets + 10), log2, seed=1)
    await em2.start()
    for seq in range(1, n_packets + 1):
        em2.datagram_received(_data(seq), fake_sender)

    # Wait long enough for all call_later callbacks to fire.
    await asyncio.sleep(expected_ser_total + 0.5)
    forwards = log2.of_kind("forward")
    assert len(forwards) == n_packets, (
        f"Expected {n_packets} forwards, got {len(forwards)}"
    )
    await em2.stop()
    sink.close()


@pytest.mark.asyncio
async def test_bottleneck_virtual_time_scales_with_bandwidth():
    """Halving bandwidth should exactly double the virtual serialisation span.

    Tests the virtual-time model directly, not wall-clock delivery timing.
    """
    n_packets = 500
    raw = _data(1)
    packet_bits = len(raw) * 8

    def _virtual_span(bw_kbps: float) -> float:
        """Feed packets and return _next_free - start_time (virtual span)."""
        log = RunLog()
        em = Emulator(("127.0.0.1", 9000), ("127.0.0.1", 9001),
                      Conditions(delay_ms=0, loss_pct=0, bandwidth_kbps=bw_kbps,
                                 queue_pkts=n_packets + 10), log, seed=1)
        t0 = time.perf_counter()
        fake_sender = ("127.0.0.1", 55555)
        for seq in range(1, n_packets + 1):
            em.datagram_received(_data(seq), fake_sender)
        return em._next_free - t0

    span_fast = _virtual_span(8000)
    span_slow = _virtual_span(4000)

    # Virtual model is precise: ratio should be very close to 2.0.
    ratio = span_slow / span_fast
    assert 1.9 < ratio < 2.1, (
        f"Expected ratio ~2.0, got {ratio:.4f} "
        f"(fast={span_fast:.6f}s, slow={span_slow:.6f}s)"
    )

    # Also verify absolute values.
    expected_fast = n_packets * packet_bits / (8000 * 1000)
    expected_slow = n_packets * packet_bits / (4000 * 1000)
    assert span_fast == pytest.approx(expected_fast, rel=0.15)
    assert span_slow == pytest.approx(expected_slow, rel=0.15)
