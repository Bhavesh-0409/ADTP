"""Fixed-window reference controller: constant window, never reacts to loss.
Useful as a sanity check for the sender (reliability only) and as a 'no congestion control' bound."""

from __future__ import annotations

from typing import Optional

from .base import CongestionController, LossDecision


class FixedWindowController(CongestionController):
    name = "fixed"

    def __init__(self, window: int = 10) -> None:
        super().__init__(initial_cwnd=window, initial_ssthresh=window)
        self._fixed = float(window)

    def on_ack(self, newly_acked: int, rtt: Optional[float], base_rtt: Optional[float]) -> None:
        pass

    def on_dup_ack(self) -> None:
        pass

    def _decision(self, trigger: str) -> LossDecision:
        return LossDecision(trigger, "unclassified", None, self.cwnd, self.cwnd, self.ssthresh,
                            f"Fixed window ({int(self._fixed)}): no reaction to loss")

    def on_triple_dup_ack(self, rtt: Optional[float], base_rtt: Optional[float]) -> LossDecision:
        return self._decision("dupack")

    def on_timeout(self, rtt: Optional[float], base_rtt: Optional[float]) -> LossDecision:
        return self._decision("timeout")
