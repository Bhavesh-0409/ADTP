import React, { useMemo } from "react";

export default function ProtocolPanel({ events = [], currentTime = 0 }) {
  // Compute current connection state, phase, and latest packets up to currentTime
  const { connState, phase, curCwnd, curRtt, curBaseRtt, recentPackets } = useMemo(() => {
    let state = "ESTABLISHED";
    let curPhase = "slow_start";
    let cwnd = 1.0;
    let rtt = null;
    let baseRtt = null;
    const packets = [];

    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      if (e.t > currentTime) break;

      if (e.kind === "cwnd") {
        cwnd = e.cwnd;
        curPhase = e.phase;
      } else if (e.kind === "rtt") {
        rtt = e.rtt * 1000;
        baseRtt = e.base_rtt * 1000;
      } else if (e.kind === "forward") {
        if (e.type === "SYN") state = "SYN_SENT";
        else if (e.type === "SYN_ACK") state = "ESTABLISHED";
        else if (e.type === "FIN") state = "FIN_WAIT";
        else if (e.type === "ACK" && state === "SYN_SENT") state = "ESTABLISHED";
        packets.push({
          t: e.t,
          type: e.type,
          seq: e.seq,
          ack: e.ack,
          direction: e.direction === "sender_to_receiver" ? "S → R" : "R → S",
        });
      } else if (e.kind === "send") {
        packets.push({
          t: e.t,
          type: e.retransmit ? "RETRANS" : "DATA",
          seq: e.seq,
          ack: "-",
          direction: "S → R",
        });
      }
    }

    if (currentTime > 0 && events.length && currentTime >= events[events.length - 1].t) {
      state = "CLOSED";
    } else if (state === "SYN_SENT" && events.some((e) => e.kind === "send" && e.t <= currentTime)) {
      state = "ESTABLISHED";
    }

    return {
      connState: state,
      phase: curPhase,
      curCwnd: cwnd,
      curRtt: rtt,
      curBaseRtt: baseRtt,
      recentPackets: packets.slice(-8).reverse(),
    };
  }, [events, currentTime]);

  return (
    <details className="glass-card inspector">
      <summary className="inspector-summary">
        <span className="section-label">
          Protocol inspector
        </span>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <span className={`badge ${connState === "ESTABLISHED" ? "badge-green" : connState === "CLOSED" ? "badge-blue" : "badge-amber"}`}>
            ● {connState}
          </span>
          <span className="badge badge-purple">
            {phase?.replace("_", " ")}
          </span>
        </div>
      </summary>

      {/* KPI Stats Strip */}
      <div className="inspector-body">
      <div className="inspector-stats">
        <div className="kpi-box compact-kpi">
          <div className="kpi-label">cwnd</div>
          <div className="inspector-number adtp-number">
            {curCwnd?.toFixed(2)}
          </div>
        </div>
        <div className="kpi-box compact-kpi">
          <div className="kpi-label">Recent RTT</div>
          <div className="inspector-number">
            {curRtt ? `${curRtt.toFixed(1)} ms` : "N/A"}
          </div>
        </div>
        <div className="kpi-box compact-kpi">
          <div className="kpi-label">Base RTT</div>
          <div className="inspector-number">
            {curBaseRtt ? `${curBaseRtt.toFixed(1)} ms` : "N/A"}
          </div>
        </div>
        <div className="kpi-box compact-kpi">
          <div className="kpi-label">MSS</div>
          <div className="inspector-number">
            1000 B
          </div>
        </div>
      </div>

      {/* Recent Packets Header Table */}
      <div className="packet-table">
        <table>
          <thead>
            <tr><th>Time</th><th>Flow</th><th>Type</th><th>Seq</th><th>Ack</th>
            </tr>
          </thead>
          <tbody>
            {recentPackets.map((pkt, idx) => (
              <tr key={idx}>
                <td>{pkt.t.toFixed(3)}s</td><td>{pkt.direction}</td><td>
                  <span className={`badge ${pkt.type === "DATA" ? "badge-blue" : pkt.type === "ACK" ? "badge-green" : pkt.type === "RETRANS" ? "badge-purple" : "badge-amber"}`}>
                    {pkt.type}
                  </span>
                </td><td>#{pkt.seq}</td><td>{pkt.ack !== "-" ? `#${pkt.ack}` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </div>
    </details>
  );
}
