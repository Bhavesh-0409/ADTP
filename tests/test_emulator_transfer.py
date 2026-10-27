"""A small end-to-end emulator check that should stay fast in normal test runs."""

import asyncio
import hashlib
import socket

import pytest

from adtp.congestion import AdtpController, RenoController
from adtp.emulator import Emulator
from adtp.metrics import RunLog, classification_accuracy
from adtp.receiver import Receiver
from adtp.scenarios import Conditions
from adtp.sender import Sender


def _port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.mark.asyncio
async def test_20kb_clean_transfer_through_emulator_finishes_under_five_seconds(tmp_path):
    source, output = tmp_path / "source.bin", tmp_path / "received.bin"
    payload = b"emulator-check" * 1_429  # 20,006 B
    source.write_bytes(payload)
    receiver_port, emulator_port = _port(), _port()
    receiver_task = asyncio.create_task(
        Receiver(("127.0.0.1", receiver_port), str(output), RunLog(), transfer_timeout=4).receive_file()
    )
    await asyncio.sleep(0)
    log = RunLog()
    emulator = Emulator(("127.0.0.1", emulator_port), ("127.0.0.1", receiver_port),
                        Conditions(delay_ms=1, bandwidth_kbps=8_000, queue_pkts=50), log, seed=7)
    await emulator.start()
    try:
        summary = await asyncio.wait_for(
            Sender(RenoController(), ("127.0.0.1", emulator_port), log, transfer_timeout=4).send_file(str(source)),
            timeout=5,
        )
        received = await receiver_task
        assert output.read_bytes() == payload
        assert received["sha256"] == hashlib.sha256(payload).hexdigest()
        assert summary["completion_time_s"] < 5
        assert any(event["direction"] == "sender_to_receiver" for event in log.of_kind("forward"))
        assert any(event["direction"] == "receiver_to_sender" for event in log.of_kind("forward"))
    finally:
        await emulator.stop()
        if not receiver_task.done():
            receiver_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receiver_task


@pytest.mark.asyncio
async def test_20kb_lossy_transfer_through_emulator_finishes_with_sha256(tmp_path):
    source, output = tmp_path / "source.bin", tmp_path / "received.bin"
    payload = b"lossy-emulator-check" * 1_000
    source.write_bytes(payload)
    receiver_port, emulator_port = _port(), _port()
    receiver_task = asyncio.create_task(
        Receiver(("127.0.0.1", receiver_port), str(output), RunLog(), transfer_timeout=4).receive_file()
    )
    await asyncio.sleep(0)
    log = RunLog()
    emulator = Emulator(("127.0.0.1", emulator_port), ("127.0.0.1", receiver_port),
                        Conditions(delay_ms=1, loss_pct=3, bandwidth_kbps=8_000, queue_pkts=100), log, seed=42)
    await emulator.start()
    try:
        await asyncio.wait_for(
            Sender(RenoController(), ("127.0.0.1", emulator_port), log, transfer_timeout=4).send_file(str(source)),
            timeout=5,
        )
        received = await receiver_task
        assert output.read_bytes() == payload
        assert received["sha256"] == hashlib.sha256(payload).hexdigest()
        assert log.of_kind("drop")
    finally:
        await emulator.stop()
        if not receiver_task.done():
            receiver_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receiver_task


@pytest.mark.asyncio
async def test_adtp_transfer_classifies_loss_and_maintains_integrity(tmp_path):
    source, output = tmp_path / "source.bin", tmp_path / "received.bin"
    payload = b"adtp-classifier-check" * 2_500  # 52,500 bytes
    source.write_bytes(payload)
    receiver_port, emulator_port = _port(), _port()
    receiver_task = asyncio.create_task(
        Receiver(("127.0.0.1", receiver_port), str(output), RunLog(), transfer_timeout=5).receive_file()
    )
    await asyncio.sleep(0)
    log = RunLog()
    emulator = Emulator(("127.0.0.1", emulator_port), ("127.0.0.1", receiver_port),
                        Conditions(delay_ms=2, loss_pct=3, bandwidth_kbps=8_000, queue_pkts=100), log, seed=42)
    await emulator.start()
    try:
        controller = AdtpController()
        summary = await asyncio.wait_for(
            Sender(controller, ("127.0.0.1", emulator_port), log, transfer_timeout=5).send_file(str(source)),
            timeout=6,
        )
        received = await receiver_task
        assert output.read_bytes() == payload
        assert received["sha256"] == hashlib.sha256(payload).hexdigest()

        loss_events = log.of_kind("loss")
        assert len(loss_events) > 0, "Expected at least one loss event"
        for ev in loss_events:
            assert ev["classification"] in ("random", "congestion")
            assert "trigger" in ev
            assert "cwnd_before" in ev
            assert "cwnd_after" in ev
            assert "reason" in ev

        accuracy_result = classification_accuracy(loss_events, log.of_kind("drop"))
        # Losses in an uncongested link with random loss
        assert accuracy_result["matched"] + accuracy_result["unmatched"] > 0
        assert accuracy_result["confusion"]["random"]["random"] > 0
    finally:
        await emulator.stop()
        if not receiver_task.done():
            receiver_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receiver_task

