import React, { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  CartesianGrid,
} from "recharts";

export default function ReplayCharts({ events = [], currentTime = 0, totalDuration = 10 }) {
  // Sample chart data to keep Recharts rendering smooth (< 300 points)
  const chartData = useMemo(() => {
    if (!events.length) return [];

    const points = [];
    let curCwnd = 1;
    let curSsthresh = null;
    let curRtt = null;
    let curBaseRtt = null;
    let curRetrans = 0;
    let bytesAcked = 0;

    const sampleStep = Math.max(0.02, totalDuration / 250);
    let nextSampleT = 0;

    for (let i = 0; i < events.length; i++) {
      const e = events[i];

      if (e.kind === "cwnd") {
        curCwnd = e.cwnd;
        // 64 is the controller's startup placeholder, not a useful plotted threshold.
        if (e.ssthresh !== 64 || curSsthresh !== null) curSsthresh = e.ssthresh;
      } else if (e.kind === "rtt") {
        curRtt = e.rtt * 1000; // ms
        curBaseRtt = e.base_rtt * 1000; // ms
      } else if (e.kind === "send" && e.retransmit) {
        curRetrans += 1;
      } else if (e.kind === "ack") {
        bytesAcked = Math.max(bytesAcked, e.ack * 1000);
      }

      if (e.t >= nextSampleT || i === events.length - 1) {
        const thpt = e.t > 0 ? Math.round((bytesAcked * 8) / (e.t * 1000)) : 0;
        points.push({
          t: Number(e.t.toFixed(3)),
          cwnd: Number(curCwnd.toFixed(2)),
          ssthresh: curSsthresh === null ? null : Number(curSsthresh.toFixed(2)),
          rtt: curRtt !== null ? Number(curRtt.toFixed(1)) : null,
          base_rtt: curBaseRtt !== null ? Number(curBaseRtt.toFixed(1)) : null,
          throughput: thpt,
          retransmissions: curRetrans,
        });
        nextSampleT = e.t + sampleStep;
      }
    }
    return points;
  }, [events, totalDuration]);

  const cwndMax = Math.max(1, ...chartData.map((point) => point.cwnd || 0));

  // Extract loss event reference markers with ground-truth colors
  const lossMarkers = useMemo(() => {
    const markers = [];
    const drops = events.filter((e) => e.kind === "drop");

    for (const e of events) {
      if (e.kind === "loss") {
        // match emulator ground-truth drop
        const match = drops.filter((d) => d.seq === e.seq && d.t <= e.t + 0.001).pop();
        const gt = match ? match.label : "unknown";
        markers.push({
          t: e.t,
          color: gt === "random" ? "#f59e0b" : "#ef4444",
          label: gt === "random" ? "R" : "Q",
        });
      }
    }
    return markers;
  }, [events]);

  const customTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div style={{
          background: "rgba(15, 23, 42, 0.95)",
          border: "1px solid var(--border)",
          padding: "0.5rem 0.75rem",
          borderRadius: "6px",
          fontFamily: "var(--font-mono)",
          fontSize: "0.75rem",
        }}>
          <div style={{ color: "var(--text-muted)", marginBottom: "0.25rem" }}>t = {label}s</div>
          {payload.map((p, idx) => (
            <div key={idx} style={{ color: p.color }}>
              {p.name}: {p.value} {p.unit || ""}
            </div>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
      {/* Chart 1: cwnd & ssthresh */}
      <div className="glass-card" style={{ padding: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
          <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>
            Congestion Window (cwnd) & ssthresh (pkts)
          </span>
          <div style={{ display: "flex", gap: "0.75rem", fontSize: "0.75rem", fontFamily: "var(--font-mono)" }}>
            <span style={{ color: "#06b6d4" }}>— cwnd</span>
            <span style={{ color: "#f59e0b" }}>┄ ssthresh</span>
          </div>
        </div>
        <div style={{ height: 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="t" stroke="var(--muted)" fontSize={12} tickFormatter={(t) => `${t}s`} />
              <YAxis stroke="var(--muted)" fontSize={12} domain={[0, Math.ceil(cwndMax * 1.1)]} />
              <Tooltip content={customTooltip} />
              {/* Scrub bar current time line */}
              <ReferenceLine x={Number(currentTime.toFixed(3))} stroke="#ffffff" strokeWidth={1.5} strokeDasharray="3 3" />
              <Line type="monotone" dataKey="cwnd" stroke="#06b6d4" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="stepAfter" dataKey="ssthresh" stroke="#FFB020" strokeWidth={1.5} strokeDasharray="5 5" dot={false} isAnimationActive={false} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart 2: RTT & Base RTT */}
      <div className="glass-card" style={{ padding: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
          <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>
            Round Trip Time: RTT vs Base RTT (ms)
          </span>
          <div style={{ display: "flex", gap: "0.75rem", fontSize: "0.75rem", fontFamily: "var(--font-mono)" }}>
            <span style={{ color: "#a855f7" }}>— recent RTT</span>
            <span style={{ color: "#10b981" }}>┄ base RTT</span>
          </div>
        </div>
        <div style={{ height: 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="t" stroke="var(--muted)" fontSize={12} tickFormatter={(t) => `${t}s`} />
              <YAxis stroke="var(--muted)" fontSize={12} unit="ms" />
              <Tooltip content={customTooltip} />
              <ReferenceLine x={Number(currentTime.toFixed(3))} stroke="#ffffff" strokeWidth={1.5} strokeDasharray="3 3" />
              <Line type="monotone" dataKey="rtt" stroke="#a855f7" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="base_rtt" stroke="#10b981" strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart 3: Throughput & Retransmissions */}
      <div className="glass-card" style={{ gridColumn: "span 2", padding: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
          <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>
            Throughput (kbps) & Cumulative Retransmissions
          </span>
          <div style={{ display: "flex", gap: "0.75rem", fontSize: "0.75rem", fontFamily: "var(--font-mono)" }}>
            <span style={{ color: "#3b82f6" }}>— Throughput</span>
            <span style={{ color: "#ef4444" }}>— Retransmissions (count)</span>
          </div>
        </div>
        <div style={{ height: 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="t" stroke="var(--muted)" fontSize={12} tickFormatter={(t) => `${t}s`} />
              <YAxis yAxisId="left" stroke="var(--muted)" fontSize={12} unit="k" />
              <YAxis yAxisId="right" orientation="right" stroke="#FF5C6C" fontSize={12} />
              <Tooltip content={customTooltip} />
              <ReferenceLine yAxisId="left" x={Number(currentTime.toFixed(3))} stroke="#ffffff" strokeWidth={1.5} strokeDasharray="3 3" />
              <Line yAxisId="left" type="monotone" dataKey="throughput" stroke="#3b82f6" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line yAxisId="right" type="stepAfter" dataKey="retransmissions" stroke="#ef4444" strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
