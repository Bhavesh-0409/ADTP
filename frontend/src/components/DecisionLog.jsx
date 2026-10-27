import React, { useMemo } from "react";

export default function DecisionLog({ events = [], currentTime = 0 }) {
  // Find all loss events up to currentTime, along with matched drop ground truth
  const decisions = useMemo(() => {
    const drops = events.filter((e) => e.kind === "drop");
    const activeLosses = [];

    for (const e of events) {
      if (e.kind === "loss" && e.t <= currentTime) {
        // Find matching drop in emulator ground truth
        const match = drops.filter((d) => d.seq === e.seq && d.t <= e.t + 0.001).pop();
        const gt = match ? match.label : "none";

        let isCorrect = false;
        if (e.classification === "random" && gt === "random") isCorrect = true;
        if (e.classification === "congestion" && gt === "queue_overflow") isCorrect = true;

        activeLosses.push({
          ...e,
          groundTruth: gt,
          isCorrect,
        });
      }
    }
    return activeLosses.reverse(); // newest first
  }, [events, currentTime]);

  const latest = decisions[0];
  const threshold = 3;
  const backlog = latest?.backlog ?? 0;
  return (
    <div className="decision-layout">
      <div className="glass-card latest-decision">
        <div className="section-label">Latest classifier decision</div>
        <div className={`decision-hero ${latest?.classification || "idle"}`}>{latest ? latest.classification.toUpperCase() : "WAITING"}</div>
        <div className="gauge-meta"><span>N = {backlog.toFixed(1)}</span><span>threshold {threshold}</span></div>
        <div className="gauge"><span style={{ width: `${Math.min(100, (backlog / 8) * 100)}%` }} /></div>
        <div className="decision-caption">{latest ? `cwnd ${latest.cwnd_before?.toFixed(0)} → ${latest.cwnd_after?.toFixed(0)}` : "Play the replay to inspect a loss decision."}</div>
      </div>
      <div className="glass-card decision-history">
      <div className="decision-heading"><span className="section-label">Decision log</span><span className="muted-mono">{decisions.length} events</span></div>
      <div className="decision-list">
        {decisions.length === 0 ? (
          <div className="empty-inline">
            No loss events yet at t = {currentTime.toFixed(2)}s
          </div>
        ) : (
          decisions.slice(0, 6).map((d, idx) => (
            <div className="decision-row" key={idx}>
              <span className="muted-mono">t={d.t.toFixed(2)}s</span>
              <span className={`decision-pill ${d.classification}`}>{d.classification?.toUpperCase()}</span>
              <span className="decision-reason">{d.reason || `N=${d.backlog?.toFixed(1)} · cwnd ${d.cwnd_before?.toFixed(0)} → ${d.cwnd_after?.toFixed(0)}`}</span>
              <span className={d.isCorrect ? "truth correct" : "truth wrong"}>{d.classification === "unclassified" ? "—" : d.isCorrect ? "✓" : "×"}</span>
            </div>
          ))
        )}
      </div>
      </div>
    </div>
  );
}
