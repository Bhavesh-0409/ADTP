"""Real localhost integration tests for build-plan steps 2 and 3."""

import asyncio
import hashlib
import socket

import pytest

from adtp.congestion import FixedWindowController, RenoController
from adtp.metrics import RunLog
from adtp.packet import Packet, PacketError, PacketType
from adtp.receiver import Receiver
from adtp.sender import Sender


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _DropOnceProxy(asyncio.DatagramProtocol):
    """Test proxy for one dropped/reordered/duplicated packet."""
    def __init__(self, target, *, drop_data=None, drop_type=None, reorder_seq=None, duplicate_seq=None):
        self.target, self.drop_data, self.drop_type = target, drop_data, drop_type
        self.reorder_seq, self.duplicate_seq = reorder_seq, duplicate_seq
        self.client = self.transport = None
        self.dropped = False
        self.held = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, raw, addr):
        try:
            packet = Packet.decode(raw)
        except PacketError:
            return
        if addr != self.target:
            self.client = addr
            if not self.dropped and ((packet.type is PacketType.DATA and packet.seq == self.drop_data)
                                     or packet.type is self.drop_type):
                self.dropped = True
                return
            if packet.type is PacketType.DATA and packet.seq == self.reorder_seq:
                self.held = raw
                return
            self.transport.sendto(raw, self.target)
            if (self.reorder_seq is not None and packet.type is PacketType.DATA
                    and packet.seq == self.reorder_seq + 1 and self.held):
                self.transport.sendto(self.held, self.target)
                self.held = None
            if packet.type is PacketType.DATA and packet.seq == self.duplicate_seq:
                self.transport.sendto(raw, self.target)
        elif self.client is not None:
            self.transport.sendto(raw, self.client)


async def _transfer(tmp_path, data, *, proxy=None, window=8, controller=None):
    receiver_port = _free_port()
    source, output = tmp_path / "source.bin", tmp_path / "output.bin"
    source.write_bytes(data)
    receiver_task = asyncio.create_task(
        Receiver(("127.0.0.1", receiver_port), str(output), RunLog(), transfer_timeout=5).receive_file())
    # Let the task bind its UDP socket before the sender's first SYN.
    await asyncio.sleep(0)
    remote, proxy_transport = ("127.0.0.1", receiver_port), None
    if proxy is not None:
        proxy.target = remote
        proxy_transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: proxy, local_addr=("127.0.0.1", 0))
        remote = ("127.0.0.1", proxy_transport.get_extra_info("sockname")[1])
    log = RunLog()
    try:
        result = await Sender(controller or FixedWindowController(window), remote, log,
                              transfer_timeout=20).send_file(str(source))
        return output, result, await receiver_task, log
    finally:
        if proxy_transport:
            proxy_transport.close()
        if not receiver_task.done():
            receiver_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receiver_task


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 1, 1000, 1001, 2_000_000])
async def test_handshake_and_clean_transfer_checksum_matches(tmp_path, size):
    """Handshake + clean SHA-256 transfer: 0 B, 1 B, MSS, MSS+1, and 2 MB."""
    data = b"x" * size
    output, _, received, log = await _transfer(tmp_path, data)
    assert output.read_bytes() == data
    assert received == {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    assert log.of_kind("loss") == []


@pytest.mark.asyncio
async def test_lost_middle_packet_uses_triple_duplicate_ack_fast_retransmit(tmp_path):
    proxy = _DropOnceProxy(("127.0.0.1", 0), drop_data=2)
    data = b"x" * 6_000
    output, _, _, log = await _transfer(tmp_path, data, proxy=proxy, window=6)
    assert proxy.dropped and output.read_bytes() == data
    assert any(e["trigger"] == "dupack" and e["seq"] == 2 for e in log.of_kind("loss"))
    assert any(e["seq"] == 2 and e["retransmit"] for e in log.of_kind("send"))


@pytest.mark.asyncio
async def test_lost_tail_packet_uses_rto_timeout_retransmit(tmp_path):
    proxy = _DropOnceProxy(("127.0.0.1", 0), drop_data=3)
    data = b"x" * 3_000
    output, _, _, log = await _transfer(tmp_path, data, proxy=proxy, window=3)
    assert proxy.dropped and output.read_bytes() == data
    assert any(e["trigger"] == "timeout" and e["seq"] == 3 for e in log.of_kind("loss"))


@pytest.mark.asyncio
async def test_dropped_syn_is_retried(tmp_path):
    proxy = _DropOnceProxy(("127.0.0.1", 0), drop_type=PacketType.SYN)
    output, _, _, _ = await _transfer(tmp_path, b"syn retry", proxy=proxy)
    assert proxy.dropped and output.read_bytes() == b"syn retry"


@pytest.mark.asyncio
async def test_dropped_fin_is_retried(tmp_path):
    proxy = _DropOnceProxy(("127.0.0.1", 0), drop_type=PacketType.FIN)
    output, _, _, _ = await _transfer(tmp_path, b"fin retry", proxy=proxy)
    assert proxy.dropped and output.read_bytes() == b"fin retry"


@pytest.mark.asyncio
async def test_out_of_order_packets_are_delivered_in_order(tmp_path):
    proxy = _DropOnceProxy(("127.0.0.1", 0), reorder_seq=1)
    data = b"a" * 2_500
    output, _, _, _ = await _transfer(tmp_path, data, proxy=proxy, window=4)
    assert output.read_bytes() == data


@pytest.mark.asyncio
async def test_duplicate_packets_are_not_written_twice(tmp_path):
    proxy = _DropOnceProxy(("127.0.0.1", 0), duplicate_seq=1)
    data = b"b" * 2_500
    output, _, received, _ = await _transfer(tmp_path, data, proxy=proxy, window=4)
    assert output.read_bytes() == data and received["bytes"] == len(data)


@pytest.mark.asyncio
async def test_reno_sender_logs_slow_start_ca_and_halves_ssthresh_on_drop(tmp_path):
    proxy = _DropOnceProxy(("127.0.0.1", 0), drop_data=12)
    controller = RenoController(initial_ssthresh=8)
    _, _, _, log = await _transfer(tmp_path, b"r" * 50_000, proxy=proxy, controller=controller)
    phases = {event["phase"] for event in log.of_kind("cwnd")}
    loss = next(event for event in log.of_kind("loss") if event["trigger"] == "dupack")
    assert {"slow_start", "congestion_avoidance", "fast_recovery"} <= phases
    assert loss["cwnd_after"] == pytest.approx(max(loss["cwnd_before"] * 0.5, 2.0) + 3)
