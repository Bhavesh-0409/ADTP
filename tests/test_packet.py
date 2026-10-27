import struct
import zlib

import pytest

from adtp.config import MSS
from adtp.packet import (HEADER_FMT, HEADER_SIZE, ChecksumError, Packet, PacketError,
                         PacketType, now_us)


@pytest.mark.parametrize("ptype", list(PacketType))
def test_roundtrip_every_type(ptype):
    p = Packet(ptype, seq=7, ack=9, window=64, ts=123456, ts_echo=654321)
    assert Packet.decode(p.encode()) == p


def test_roundtrip_with_payload():
    p = Packet(PacketType.DATA, seq=1, payload=b"hello" * 100)
    q = Packet.decode(p.encode())
    assert q.payload == p.payload and q.seq == 1


def test_max_values_roundtrip():
    p = Packet(PacketType.ACK, seq=2**32 - 1, ack=2**32 - 1, window=65535, ts=2**63, ts_echo=2**63)
    assert Packet.decode(p.encode()) == p


def test_header_size_is_33():
    assert HEADER_SIZE == 33
    assert len(Packet(PacketType.SYN).encode()) == 33


def test_full_mss_payload_ok_and_oversize_rejected():
    assert len(Packet(PacketType.DATA, payload=b"x" * MSS).encode()) == HEADER_SIZE + MSS
    with pytest.raises(PacketError):
        Packet(PacketType.DATA, payload=b"x" * (MSS + 1)).encode()


@pytest.mark.parametrize("pos", [0, 5, 20, HEADER_SIZE + 3])
def test_bit_flip_detected(pos):
    raw = bytearray(Packet(PacketType.DATA, seq=3, payload=b"abcdefgh").encode())
    raw[pos] ^= 0x01
    with pytest.raises(PacketError):  # ChecksumError, or a length/type error if the flip hit those fields
        Packet.decode(bytes(raw))


def test_payload_corruption_is_checksum_error():
    raw = bytearray(Packet(PacketType.DATA, payload=b"abcdefgh").encode())
    raw[-1] ^= 0xFF
    with pytest.raises(ChecksumError):
        Packet.decode(bytes(raw))


def test_truncated_and_empty():
    raw = Packet(PacketType.DATA, payload=b"abcdefgh").encode()
    for bad in (b"", raw[: HEADER_SIZE - 1], raw[:-1]):
        with pytest.raises(PacketError):
            Packet.decode(bad)


def test_trailing_garbage_rejected():
    raw = Packet(PacketType.ACK).encode()
    with pytest.raises(PacketError):
        Packet.decode(raw + b"\x00")


def test_unknown_type_rejected_even_with_valid_checksum():
    hdr = struct.pack(HEADER_FMT, 99, 0, 0, 0, 0, 0, 0, 0)
    crc = zlib.crc32(hdr) & 0xFFFFFFFF
    raw = hdr[:-4] + struct.pack("!I", crc)
    with pytest.raises(PacketError, match="unknown packet type"):
        Packet.decode(raw)


def test_summary_and_clock():
    s = Packet(PacketType.DATA, seq=4, payload=b"ab").summary()
    assert s["type"] == "DATA" and s["seq"] == 4 and s["len"] == 2
    assert now_us() <= now_us()
