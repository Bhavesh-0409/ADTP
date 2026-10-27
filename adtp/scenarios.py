"""Scenario definitions (data only). The runner (runner.py) executes them.

All numbers are STARTING POINTS. Tune them once the emulator works so the effect is visible
(e.g. the congested scenario must actually overflow the queue; the lossy one must not).

Handy arithmetic: bandwidth-delay product (BDP) in packets ~= bandwidth * RTT / packet_size.
  clean:     8 Mbps * 40 ms / (1033 B * 8) ~ 39 packets  (queue 50 -> window can fill the pipe)
  congested: 2 Mbps * 40 ms / (1033 B * 8) ~  9 packets  (queue 10 -> overflow once cwnd > ~19)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Conditions:
    delay_ms: float = 20.0        # one-way delay (RTT ~ 2x, ACKs get the same delay)
    loss_pct: float = 0.0         # random loss probability, percent, per packet
    bandwidth_kbps: float = 8000  # bottleneck rate; 0 = unlimited
    queue_pkts: int = 50          # drop-tail queue size at the bottleneck


@dataclass
class Scenario:
    key: str
    title: str
    description: str
    file_bytes: int
    initial: Conditions
    changes: list[tuple[float, dict]] = field(default_factory=list)  # (seconds after start, {field: value})
    flows: int = 1
    optional: bool = False
    seed: int = 42

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


SCENARIOS: dict[str, Scenario] = {s.key: s for s in [
    Scenario("clean", "1. Clean link",
             "No random loss, big queue. ADTP and Reno should be about equal.",
             file_bytes=2_000_000, initial=Conditions(loss_pct=0.0, bandwidth_kbps=8000, queue_pkts=50)),
    Scenario("lossy", "2. Lossy link (random loss)",
             "Random loss, no real congestion. Reno wastes bandwidth; ADTP should win clearly.",
             file_bytes=2_000_000, initial=Conditions(loss_pct=3.0, bandwidth_kbps=8000, queue_pkts=100)),
    Scenario("congested", "3. Congested bottleneck",
             "Slow link, tiny queue, no random loss. Losses are real congestion; expect roughly equal.",
             file_bytes=2_000_000, initial=Conditions(loss_pct=0.0, bandwidth_kbps=2000, queue_pkts=10)),
    Scenario("dynamic", "4. Conditions change mid-transfer",
             "Clean for 5 s, then random loss jumps to 5%. Shows ADTP adapting.",
             file_bytes=3_000_000, initial=Conditions(loss_pct=0.0, bandwidth_kbps=8000, queue_pkts=100),
             changes=[(5.0, {"loss_pct": 5.0})]),
    Scenario("fairness", "5. Two competing flows",
             "Two flows share the bottleneck; report Jain's fairness index. Build last.",
             file_bytes=2_000_000, initial=Conditions(loss_pct=0.0, bandwidth_kbps=4000, queue_pkts=30),
             flows=2, optional=True),
]}
