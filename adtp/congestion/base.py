"""Controller interface. The sender talks ONLY to this interface, so swapping
Reno / ADTP / Fixed changes nothing else in the sender code.

Units: cwnd and ssthresh are in PACKETS (floats internally).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .. import config


@dataclass
class LossDecision:
    """What the controller decided on a loss event. Logged for the dashboard's decision log
    and used to compute classification accuracy against emulator ground truth."""

    trigger: str                    # "dupack" (triple dup-ACK) or "timeout"
    classification: str             # "random" | "congestion" | "unclassified"
    backlog: Optional[float]        # estimated queued packets (None if not computed)
    cwnd_before: float
    cwnd_after: float
    ssthresh_after: float
    reason: str                     # human-readable line for the decision log


class CongestionController(ABC):
    name = "base"

    def __init__(
        self,
        initial_cwnd: float = config.INITIAL_CWND,
        initial_ssthresh: float = config.INITIAL_SSTHRESH,
    ) -> None:
        self.cwnd = float(initial_cwnd)
        self.ssthresh = float(initial_ssthresh)
        self.in_recovery = False

    @property
    def window(self) -> int:
        """Whole packets the sender may have in flight (before flow control is applied)."""
        return max(1, int(self.cwnd))

    @property
    def phase(self) -> str:
        if self.in_recovery:
            return "fast_recovery"
        return "slow_start" if self.cwnd < self.ssthresh else "congestion_avoidance"

    @abstractmethod
    def on_ack(self, newly_acked: int, rtt: Optional[float], base_rtt: Optional[float]) -> None:
        """A NEW cumulative ACK arrived, acknowledging `newly_acked` packets."""

    @abstractmethod
    def on_dup_ack(self) -> None:
        """A duplicate ACK (beyond the one that triggered fast retransmit) arrived."""

    @abstractmethod
    def on_triple_dup_ack(self, rtt: Optional[float], base_rtt: Optional[float]) -> LossDecision:
        """Third duplicate ACK: sender is about to fast-retransmit."""

    @abstractmethod
    def on_timeout(self, rtt: Optional[float], base_rtt: Optional[float]) -> LossDecision:
        """Retransmission timer expired."""

    def snapshot(self) -> dict:
        return {"cwnd": round(self.cwnd, 3), "ssthresh": round(self.ssthresh, 3), "phase": self.phase}
