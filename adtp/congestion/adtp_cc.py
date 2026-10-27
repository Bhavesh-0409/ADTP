"""ADTP controller: Reno + a TCP-Veno-style loss classifier.

Idea (established, not novel: TCP Veno, TCP Westwood are related work):
  If the network queue is building up, RTT rises above the base RTT.
  So at the moment of loss, estimate the queue backlog:

        N = cwnd * (RTT - baseRTT) / RTT        (packets sitting in queues)

  N <  threshold (default 3) -> queue is ~empty -> loss was RANDOM (e.g. Wi-Fi noise)
                                -> mild cut: ssthresh = 0.8 * cwnd
  N >= threshold             -> queue is filling  -> loss is CONGESTION
                                -> Reno-style cut: ssthresh = 0.5 * cwnd

Everything else (slow start, congestion avoidance, fast recovery shape) is inherited from Reno,
so any performance difference is caused by the classifier alone.

Design choices to mention in the viva:
  * No RTT data yet -> fall back to Reno behaviour (safe default).
  * Timeouts: window still collapses to 1 (a timeout is a strong sign the pipe emptied),
    but the classification is still computed and used for ssthresh, then logged.
  * Known weakness: base RTT is a lifetime minimum; if the path delay rises permanently
    mid-transfer, the backlog looks permanently high (everything classified congestion).
"""

from __future__ import annotations

from typing import Optional

from .. import config
from .reno import RenoController


class AdtpController(RenoController):
    name = "adtp"

    def __init__(self, threshold: float = config.ADTP_BACKLOG_THRESHOLD,
                 random_cut: float = config.ADTP_RANDOM_CUT,
                 timeout_as_congestion: bool = config.ADTP_TIMEOUT_AS_CONGESTION, **kwargs) -> None:
        super().__init__(**kwargs)
        self.threshold = threshold
        self.random_cut = random_cut
        self.timeout_as_congestion = timeout_as_congestion

    def backlog(self, rtt: Optional[float], base_rtt: Optional[float]) -> Optional[float]:
        if not rtt or not base_rtt or rtt <= 0:
            return None
        return self.cwnd * max(0.0, rtt - base_rtt) / rtt

    def _ssthresh_on_loss(self, trigger: str, rtt: Optional[float], base_rtt: Optional[float]):
        n = self.backlog(rtt, base_rtt)
        if self.timeout_as_congestion and trigger == "timeout":
            new_ss = max(self.cwnd * config.RENO_CUT, 2.0)
            return (new_ss, "congestion", n,
                    f"timeout classified CONGESTION (--timeout-as-congestion), halve window"
                    + (f" (backlog N={n:.2f})" if n is not None else ""))
        if n is None:
            return (max(self.cwnd * config.RENO_CUT, 2.0), "congestion", None,
                    "no RTT data yet -> fall back to Reno (halve window)")
        if n < self.threshold:
            new_ss = max(self.cwnd * self.random_cut, 2.0)
            return (new_ss, "random", n,
                    f"backlog N={n:.2f} < {self.threshold:g}: RTT near base, classified RANDOM, "
                    f"small cut (x{self.random_cut:g})")
        new_ss = max(self.cwnd * config.RENO_CUT, 2.0)
        return (new_ss, "congestion", n,
                f"backlog N={n:.2f} >= {self.threshold:g}: queue building, classified CONGESTION, "
                f"halve window")
