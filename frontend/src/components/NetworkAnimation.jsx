import React, { useMemo } from "react";

export default function NetworkAnimation({ events = [], currentTime = 0, queueMax = 50, scenario = "clean" }) {
  // Extract queue depth at or just before currentTime
  const currentQueueDepth = useMemo(() => {
    let depth = 0;
    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      if (e.t > currentTime) break;
      if (e.kind === "queue" && typeof e.depth === "number") {
        depth = e.depth;
      }
    }
    return depth;
  }, [events, currentTime]);

  // Find packets currently in flight around currentTime (window of ~0.15s)
  const activePackets = useMemo(() => {
    const packets = [];
    const windowStart = Math.max(0, currentTime - 0.12);
    const windowEnd = currentTime + 0.02;

    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      if (e.t > windowEnd) break;
      if (e.t < windowStart) continue;

      if (e.kind === "send") {
        const progress = Math.min(1, Math.max(0, (currentTime - e.t) / 0.08));
        packets.push({
          id: `send-${e.seq}-${e.t}`,
          direction: "forward",
          type: e.retransmit ? "retransmit" : "send",
          color: e.retransmit ? "#a855f7" : "#3b82f6",
          progress,
          seq: e.seq,
        });
      } else if (e.kind === "drop") {
        // Show drop explosion near the bottleneck router
        if (currentTime - e.t < 0.15) {
          packets.push({
            id: `drop-${e.seq}-${e.t}`,
            direction: "drop",
            type: e.label,
            color: e.label === "random" ? "#f59e0b" : "#ef4444",
            progress: 0.5,
            seq: e.seq,
          });
        }
      } else if (e.kind === "forward" && e.direction === "receiver_to_sender") {
        const progress = Math.min(1, Math.max(0, (currentTime - e.t) / 0.08));
        packets.push({
          id: `ack-${e.ack}-${e.t}`,
          direction: "return",
          type: "ack",
          color: "#10b981",
          progress,
          seq: e.ack,
        });
      }
    }
    return packets.slice(-40);
  }, [events, currentTime]);

  const queuePct = Math.min(100, Math.round((currentQueueDepth / (queueMax || 50)) * 100));

  return (
    <div className="glass-card network-card">
      {/* Header and Legend */}
      <div className="network-heading">
        <div className="network-title">
          <span className="section-label">Network flow</span>
          <span className="badge badge-blue">
            {scenario} link
          </span>
        </div>

        {/* Legend */}
        <div className="legend">
          <span><i className="dot sent" /> Sent</span><span><i className="dot ack" /> ACK</span><span><i className="dot random" /> Random loss</span><span><i className="dot congestion" /> Congestion</span><span><i className="dot retransmit" /> Retransmit</span>
        </div>
      </div>

      {/* SVG Animation Canvas */}
      <svg viewBox="0 0 900 170" className="network-svg">
        {/* Background Grid Lines */}
        <defs>
          <linearGradient id="forwardWire" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.6" />
            <stop offset="50%" stopColor="#6366f1" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.6" />
          </linearGradient>
          <linearGradient id="returnWire" x1="100%" y1="0%" x2="0%" y2="0%">
            <stop offset="0%" stopColor="#10b981" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0.3" />
          </linearGradient>
          <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Forward wire (Sender -> Router -> Receiver) */}
        <path d="M 140 65 L 400 65 L 500 65 L 760 65" fill="none" stroke="url(#forwardWire)" strokeWidth="3" strokeDasharray="6 4" opacity="0.7" />
        <text x="450" y="45" textAnchor="middle" fill="var(--muted)" fontSize="12" fontFamily="var(--font-mono)">
          FORWARD (DATA & BOTTLENECK) →
        </text>

        {/* Return wire (Receiver -> Sender) */}
        <path d="M 760 125 L 140 125" fill="none" stroke="url(#returnWire)" strokeWidth="2.5" strokeDasharray="4 4" opacity="0.6" />
        <text x="450" y="145" textAnchor="middle" fill="var(--muted)" fontSize="12" fontFamily="var(--font-mono)">
          ← RETURN PATH (PROPAGATION ONLY / ACKs)
        </text>

        {/* Sender Node */}
        <g transform="translate(70, 40)">
          <rect width="70" height="90" rx="10" fill="#1e293b" stroke="#3b82f6" strokeWidth="2" filter="drop-shadow(0 4px 10px rgba(59,130,246,0.3))" />
          <circle cx="35" cy="25" r="8" fill="#3b82f6" />
          <text x="35" y="52" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="700">SENDER</text>
          <text x="35" y="68" textAnchor="middle" fill="#60a5fa" fontSize="9" fontFamily="var(--font-mono)">ADTP/UDP</text>
        </g>

        {/* Bottleneck Router / Queue Node */}
        <g transform="translate(390, 30)">
          <rect width="120" height="95" rx="12" fill="#1e293b" stroke={queuePct > 80 ? "#ef4444" : "#6366f1"} strokeWidth="2" filter="drop-shadow(0 4px 12px rgba(99,102,241,0.25))" />
          <text x="60" y="22" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="700">BOTTLENECK</text>
          <text x="60" y="36" textAnchor="middle" fill="var(--text-muted)" fontSize="9" fontFamily="var(--font-mono)">Router Queue</text>

          {/* Queue Bar Container */}
          <rect x="15" y="48" width="90" height="18" rx="4" fill="#090d16" stroke="rgba(255,255,255,0.1)" />
          {/* Filled Queue Depth */}
          <rect
            x="15"
            y="48"
            width={Math.max(0, (90 * queuePct) / 100)}
            height="18"
            rx="4"
            fill={queuePct > 80 ? "#ef4444" : queuePct > 50 ? "#f59e0b" : "#06b6d4"}
            style={{ transition: "width 0.1s ease" }}
          />
          <text x="60" y="61" textAnchor="middle" fill="#fff" fontSize="10" fontWeight="700" fontFamily="var(--font-mono)">
            {currentQueueDepth} / {queueMax}
          </text>

          {/* Queue Occupancy Label */}
          <text x="60" y="82" textAnchor="middle" fill={queuePct > 80 ? "#FF5C6C" : "var(--muted)"} fontSize="12" fontFamily="var(--font-mono)">
            {queuePct}% buffer
          </text>
        </g>

        {/* Receiver Node */}
        <g transform="translate(760, 40)">
          <rect width="70" height="90" rx="10" fill="#1e293b" stroke="#10b981" strokeWidth="2" filter="drop-shadow(0 4px 10px rgba(16,185,129,0.3))" />
          <circle cx="35" cy="25" r="8" fill="#10b981" />
          <text x="35" y="52" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="700">RECEIVER</text>
          <text x="35" y="68" textAnchor="middle" fill="#34d399" fontSize="9" fontFamily="var(--font-mono)">Sink/SHA</text>
        </g>

        {/* Dynamic Flying Packets */}
        {activePackets.map((p) => {
          let cx = 0;
          let cy = 65;

          if (p.direction === "forward") {
            // Sender (140) to Receiver (760)
            cx = 140 + p.progress * (760 - 140);
            cy = 65;
          } else if (p.direction === "return") {
            // Receiver (760) to Sender (140)
            cx = 760 - p.progress * (760 - 140);
            cy = 125;
          } else if (p.direction === "drop") {
            // Drop burst near the bottleneck router (x=450)
            cx = 450;
            cy = 65;
            return (
              <g key={p.id}>
                <circle cx={cx} cy={cy} r="14" fill="none" stroke={p.color} strokeWidth="2" opacity="0.8" />
                <circle cx={cx} cy={cy} r="6" fill={p.color} filter="url(#glow)" />
                <title>{`${p.type} loss, seq ${p.seq}`}</title>
              </g>
            );
          }

          return (
            <g key={p.id}>
              <circle cx={cx} cy={cy} r="5" fill={p.color} filter="url(#glow)" />
              <title>{`${p.type}, seq ${p.seq}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
