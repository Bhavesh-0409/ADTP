"""Metrics and logging: event log, JSON/CSV export, classification accuracy.

Event kinds (suggested; keep the names stable because the dashboard reads them):
  cwnd      {cwnd, ssthresh, phase}                      periodic + on change
  rtt       {rtt, srtt, rto, base_rtt}                   one per RTT sample
  send      {seq, retransmit}                            every DATA packet sent
  ack       {ack}                                        every ACK received
  loss      {seq, trigger, classification, backlog, cwnd_before, cwnd_after, reason}
  drop      {seq, label, where}                          emulator ground truth (label: random | queue_overflow)
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# classifier output -> emulator ground-truth label
CLASS_TO_LABEL = {"random": "random", "congestion": "queue_overflow"}


@dataclass
class RunLog:
    meta: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    _t0: float = field(default_factory=time.monotonic, repr=False)
    listeners: list[Callable[[dict], None]] = field(default_factory=list, repr=False)

    def add(self, kind: str, t: Optional[float] = None, **data: Any) -> dict:
        ev = {"t": round((time.monotonic() - self._t0) if t is None else t, 6), "kind": kind, **data}
        self.events.append(ev)
        for fn in self.listeners:       # lets the API push events to the WebSocket live
            fn(ev)
        return ev

    def of_kind(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["kind"] == kind]

    # ---- export ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {"meta": self.meta, "summary": self.summary, "events": self.events}

    def save_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1))
        return path

    def save_csv(self, path: str | Path) -> Path:
        """Flat CSV of all events (union of keys as columns) for spreadsheets / matplotlib."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cols: list[str] = []
        for e in self.events:
            for k in e:
                if k not in cols:
                    cols.append(k)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(self.events)
        return path

    @staticmethod
    def load_json(path: str | Path) -> "RunLog":
        d = json.loads(Path(path).read_text())
        return RunLog(meta=d.get("meta", {}), events=d.get("events", []), summary=d.get("summary", {}))


def summarize(completion_time: float, file_bytes: int, rtt_samples: list[float],
              retransmissions: int, packets_sent: int) -> dict:
    """Per-run headline numbers."""
    return {
        "completion_time_s": round(completion_time, 4),
        "throughput_kbps": round(file_bytes * 8 / 1000 / completion_time, 2) if completion_time > 0 else 0.0,
        "avg_rtt_ms": round(1000 * sum(rtt_samples) / len(rtt_samples), 3) if rtt_samples else None,
        "retransmissions": retransmissions,
        "packets_sent": packets_sent,
    }


def classification_accuracy(decisions: list[dict], drops: list[dict]) -> dict:
    """Compare ADTP's per-loss classification with the emulator's ground truth.

    decisions: 'loss' events  -> need t, seq, classification ('random' | 'congestion')
    drops:     'drop' events  -> need t, seq, label ('random' | 'queue_overflow')

    For each decision we look up the most recent emulator drop of the SAME seq at or before the
    decision time. Decisions with no matching drop (e.g. spurious retransmits caused by delay or
    reordering) are counted as 'unmatched' and excluded from accuracy.
    """
    by_seq: dict[int, list[dict]] = {}
    for d in drops:
        by_seq.setdefault(d["seq"], []).append(d)

    confusion = {"random": {"random": 0, "queue_overflow": 0},
                 "congestion": {"random": 0, "queue_overflow": 0}}
    unmatched = 0
    for dec in decisions:
        cls = dec.get("classification")
        if cls not in CLASS_TO_LABEL:          # e.g. Reno / Fixed ("unclassified")
            continue
        candidates = [d for d in by_seq.get(dec["seq"], []) if d["t"] <= dec["t"] + 1e-9]
        if not candidates:
            unmatched += 1
            continue
        truth = max(candidates, key=lambda d: d["t"])["label"]
        confusion[cls][truth] += 1

    correct = confusion["random"]["random"] + confusion["congestion"]["queue_overflow"]
    total = sum(sum(row.values()) for row in confusion.values())
    return {
        "accuracy": round(correct / total, 4) if total else None,
        "matched": total,
        "unmatched": unmatched,
        # rows = ADTP said, columns = ground truth
        "confusion": confusion,
    }
