"""TCP Reno baseline.

Reno's one big assumption: EVERY loss means congestion -> halve the window.

Phases:
  slow start            cwnd < ssthresh : cwnd += 1 per ACKed packet (doubles each RTT)
  congestion avoidance  cwnd >= ssthresh: cwnd += 1/cwnd per ACKed packet (+1 per RTT)
  fast retransmit/recovery (3 dup-ACKs): ssthresh = cwnd/2, cwnd = ssthresh + 3,
                          inflate +1 per further dup-ACK, deflate to ssthresh on the next new ACK
  timeout               : ssthresh = cwnd/2, cwnd = 1, back to slow start

Known simplification: plain Reno (exits recovery on the first new ACK), not NewReno.
Several losses in one window may therefore end in a timeout. Same for ADTP (it subclasses
this), so the comparison stays fair.
"""

from __future__ import annotations

from typing import Optional

from .. import config
from .base import CongestionController, LossDecision


class RenoController(CongestionController):
    name = "reno"

    # ---- growth ----------------------------------------------------------
    def on_ack(self, newly_acked: int, rtt: Optional[float], base_rtt: Optional[float]) -> None:
        if self.in_recovery:
            # New ACK ends fast recovery: deflate the window.
            self.cwnd = self.ssthresh
            self.in_recovery = False
            return
        if self.cwnd < self.ssthresh:
            self.cwnd += newly_acked                      # slow start
        else:
            self.cwnd += newly_acked / self.cwnd          # congestion avoidance

    def on_dup_ack(self) -> None:
        if self.in_recovery:
            self.cwnd += 1                                # window inflation

    # ---- loss ------------------------------------------------------------
    def _ssthresh_on_loss(self, trigger: str, rtt: Optional[float], base_rtt: Optional[float]):
        """Hook ADTP overrides. Returns (new_ssthresh, classification, backlog, reason)."""
        new_ss = max(self.cwnd * config.RENO_CUT, 2.0)
        return new_ss, "unclassified", None, "Reno: every loss treated as congestion, halve window"

    def on_triple_dup_ack(self, rtt: Optional[float], base_rtt: Optional[float]) -> LossDecision:
        before = self.cwnd
        ss, cls, backlog, reason = self._ssthresh_on_loss("dupack", rtt, base_rtt)
        self.ssthresh = ss
        self.cwnd = ss + 3                                # +3 for the 3 packets that left the network
        self.in_recovery = True
        return LossDecision("dupack", cls, backlog, before, self.cwnd, self.ssthresh, reason)

    def on_timeout(self, rtt: Optional[float], base_rtt: Optional[float]) -> LossDecision:
        before = self.cwnd
        ss, cls, backlog, reason = self._ssthresh_on_loss("timeout", rtt, base_rtt)
        # A timeout means the pipe has drained or ACKs stopped: always restart from 1 packet.
        self.ssthresh = ss
        self.cwnd = 1.0
        self.in_recovery = False
        return LossDecision("timeout", cls, backlog, before, self.cwnd, self.ssthresh, reason)
