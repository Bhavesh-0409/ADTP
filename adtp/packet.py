"""ADTP packet format: encode / decode with checksum.

Header (big-endian / network order), 33 bytes:

    offset size field
    0      1    type       (PacketType)
    1      4    seq        (packet number, NOT bytes)
    5      4    ack        (cumulative: next packet number the receiver expects)
    9      2    window     (receiver's advertised window, in packets)
    11     8    ts         (sender's clock when this packet was sent, microseconds)
    19     8    ts_echo    (the ts of the packet being acknowledged, echoed back -> RTT)
    27     2    length     (payload bytes)
    29     4    checksum   (CRC32 over header-with-checksum-zeroed + payload)

Why these fields (viva-ready):
  * seq/ack in packets keeps the maths simple (window size and seq share a unit).
  * ts + ts_echo give an RTT sample on every ACK without extra state.
  * checksum lets the receiver silently drop corrupted packets (UDP only has an optional one).
"""

from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass
from enum import IntEnum

from .config import MSS

HEADER_FMT = "!BIIHQQHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 33


class PacketType(IntEnum):
    SYN = 1
    SYN_ACK = 2
    ACK = 3
    DATA = 4
    FIN = 5


class PacketError(ValueError):
    """Packet could not be decoded (too short, bad length, unknown type)."""


class ChecksumError(PacketError):
    """Checksum mismatch: packet was corrupted in transit."""


def now_us() -> int:
    """Monotonic clock in microseconds (used for ts / ts_echo)."""
    return int(time.monotonic() * 1_000_000)


@dataclass
class Packet:
    type: PacketType
    seq: int = 0
    ack: int = 0
    window: int = 0
    ts: int = 0
    ts_echo: int = 0
    payload: bytes = b""

    def encode(self) -> bytes:
        if len(self.payload) > MSS:
            raise PacketError(f"payload {len(self.payload)} B exceeds MSS {MSS}")
        header = struct.pack(
            HEADER_FMT, int(self.type), self.seq, self.ack, self.window,
            self.ts, self.ts_echo, len(self.payload), 0,
        )
        checksum = zlib.crc32(header + self.payload) & 0xFFFFFFFF
        header = header[:-4] + struct.pack("!I", checksum)
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "Packet":
        if len(data) < HEADER_SIZE:
            raise PacketError(f"too short: {len(data)} < {HEADER_SIZE}")
        (ptype, seq, ack, window, ts, ts_echo, length, checksum) = struct.unpack(
            HEADER_FMT, data[:HEADER_SIZE]
        )
        if len(data) != HEADER_SIZE + length:
            raise PacketError(f"length mismatch: header says {length}, got {len(data) - HEADER_SIZE}")
        payload = data[HEADER_SIZE:]
        zeroed = data[: HEADER_SIZE - 4] + b"\x00\x00\x00\x00"
        if zlib.crc32(zeroed + payload) & 0xFFFFFFFF != checksum:
            raise ChecksumError("checksum mismatch")
        try:
            ptype = PacketType(ptype)
        except ValueError as e:
            raise PacketError(f"unknown packet type {ptype}") from e
        return cls(ptype, seq, ack, window, ts, ts_echo, payload)

    def summary(self) -> dict:
        """Header fields as a dict (for the dashboard's packet log / protocol inspector)."""
        return {
            "type": self.type.name, "seq": self.seq, "ack": self.ack,
            "window": self.window, "ts": self.ts, "ts_echo": self.ts_echo,
            "len": len(self.payload),
        }
