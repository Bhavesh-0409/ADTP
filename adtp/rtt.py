"""RTT estimation: SRTT / RTTVAR -> RTO (RFC 6298), plus base RTT for the ADTP classifier.

Two separate jobs:
  * RTO (retransmission timeout): SRTT + 4*RTTVAR. Decides WHEN to give up waiting for an ACK.
  * base_rtt = minimum RTT ever seen ~ the path's RTT with empty queues.
    (current RTT - base_rtt) approximates queueing delay, which is what ADTP uses
    to tell congestion from random loss.

Karn's rule: never take an RTT sample from a retransmitted packet (the ACK is ambiguous).
The sender is responsible for honouring that.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from . import config


class RttEstimator:
    ALPHA = 1 / 8
    BETA = 1 / 4
    K = 4

    def __init__(
        self,
        initial_rto: float = config.RTO_INITIAL,
        min_rto: float = config.RTO_MIN,
        max_rto: float = config.RTO_MAX,
        recent_window: int = config.RTT_RECENT_WINDOW,
    ) -> None:
        self.min_rto = min_rto
        self.max_rto = max_rto
        self.srtt: Optional[float] = None
        self.rttvar: Optional[float] = None
        self.rto = initial_rto
        self.base_rtt: Optional[float] = None
        self._recent: deque[float] = deque(maxlen=recent_window)

    def update(self, rtt: float) -> None:
        """Feed one RTT sample (seconds)."""
        if rtt <= 0:
            return
        if self.srtt is None:
            self.srtt = rtt
            self.rttvar = rtt / 2
        else:
            self.rttvar = (1 - self.BETA) * self.rttvar + self.BETA * abs(self.srtt - rtt)
            self.srtt = (1 - self.ALPHA) * self.srtt + self.ALPHA * rtt
        self.rto = min(self.max_rto, max(self.min_rto, self.srtt + self.K * self.rttvar))
        self.base_rtt = rtt if self.base_rtt is None else min(self.base_rtt, rtt)
        self._recent.append(rtt)

    def backoff(self) -> None:
        """Exponential backoff after a timeout."""
        self.rto = min(self.max_rto, self.rto * 2)

    @property
    def recent_rtt(self) -> Optional[float]:
        """Mean of the last few samples. Less noisy than one sample, faster than SRTT."""
        if not self._recent:
            return None
        return sum(self._recent) / len(self._recent)
