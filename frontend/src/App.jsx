import { useEffect, useMemo, useState } from "react";
import {
  BarChart, Bar, CartesianGrid, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import ControlPanel from "./components/ControlPanel";
import DecisionLog from "./components/DecisionLog";
import Navbar from "./components/Navbar";
import NetworkAnimation from "./components/NetworkAnimation";
import ProtocolPanel from "./components/ProtocolPanel";
import ReplayCharts from "./components/ReplayCharts";

const API_ERROR = "API offline. Start FastAPI on port 8000, then refresh.";

function formatNumber(value, digits = 1) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(digits);
}

function ResultCard({ label, value, tone = "cyan" }) {
  return (
    <div className="kpi-box">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value tone-${tone}`}>{value}</div>
    </div>
  );
}

function HowItWorks() {
  return (
    <section className="page-grid narrow">
      <div className="hero glass-card">
        <span className="eyebrow">For the viva</span>
        <h2>How ADTP decides what a loss means</h2>
        <p>ADTP follows TCP Veno: measure queue backlog from RTT, then choose a small or large window cut.</p>
      </div>
      <div className="steps-grid">
        <article className="glass-card info-card"><strong>1 · Reno</strong><p>Halves on every loss.</p></article>
        <article className="glass-card info-card"><strong>2 · ADTP</strong><p>Measures <code>N = cwnd × (RTT − baseRTT) / RTT</code>.</p></article>
        <article className="glass-card info-card"><strong>3 · Decision</strong><p><code>N &lt; 3</code> random: small cut. <code>N ≥ 3</code> congestion: halve.</p></article>
      </div>
      <div className="glass-card note">
        <strong>Framing:</strong> TCP Veno-style, not claimed as novel.
      </div>
    </section>
  );
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [savedRuns, setSavedRuns] = useState([]);
  const [activeTab, setActiveTab] = useState("replay");
  const [run, setRun] = useState(null);
  const [runName, setRunName] = useState("");
  const [sideBySide, setSideBySide] = useState(null);
  const [error, setError] = useState("");
  const [scenario, setScenario] = useState("lossy");
  const [controller, setController] = useState("adtp");
  const [seed, setSeed] = useState(42);
  const [size, setSize] = useState(500000);
  const [isRunning, setIsRunning] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [currentTime, setCurrentTime] = useState(0);

  const loadSavedRuns = () => fetch("/api/results").then((r) => {
    if (!r.ok) throw new Error(API_ERROR);
    return r.json();
  }).then((items) => {
    setSavedRuns(items);
    const preferred = items.find((item) => item.name === "lossy_adtp_42") || items[0];
    if (preferred && !runName) {
      setRunName(preferred.name);
      return fetch(`/api/results/${encodeURIComponent(preferred.name)}`).then((response) => response.json()).then(setRun);
    }
    return null;
  });

  useEffect(() => {
    Promise.all([
      fetch("/api/meta").then((r) => { if (!r.ok) throw new Error(API_ERROR); return r.json(); }),
      loadSavedRuns(),
    ]).then(([metadata]) => setMeta(metadata)).catch((e) => setError(e.message || API_ERROR));
  }, []);

  const events = run?.events || [];
  const totalDuration = events.length ? Math.max(events[events.length - 1].t, 0.1) : 0.1;
  const scenarioInfo = meta?.scenarios?.[scenario];

  useEffect(() => {
    if (!isPlaying || !events.length) return undefined;
    const timer = window.setInterval(() => {
      setCurrentTime((time) => {
        const next = time + 0.025 * speed;
        if (next >= totalDuration) {
          setIsPlaying(false);
          return totalDuration;
        }
        return next;
      });
    }, 25);
    return () => window.clearInterval(timer);
  }, [isPlaying, speed, totalDuration, events.length]);

  const selectRun = (name) => {
    setRunName(name);
    setIsPlaying(false);
    if (!name) return;
    fetch(`/api/results/${encodeURIComponent(name)}`).then((r) => {
      if (!r.ok) throw new Error("Could not load saved result.");
      return r.json();
    }).then((data) => {
      setRun(data);
      setCurrentTime(0);
      setError("");
    }).catch((e) => setError(e.message));
  };

  const startRun = async () => {
    setIsRunning(true);
    setError("");
    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario, controller, seed, size }),
      });
      if (!response.ok) throw new Error("Could not start run.");
      const { run_id: runId } = await response.json();
      let status;
      do {
        await new Promise((resolve) => window.setTimeout(resolve, 700));
        status = await fetch(`/api/runs/${runId}`).then((r) => r.json());
      } while (status.status === "running");
      if (status.status !== "completed") throw new Error(status.error || "Run failed.");
      const name = status.result_name;
      setRunName(name);
      setRun(await fetch(`/api/results/${encodeURIComponent(name)}`).then((r) => r.json()));
      setCurrentTime(0);
      await loadSavedRuns();
    } catch (e) {
      setError(e.message || "Run failed.");
    } finally {
      setIsRunning(false);
    }
  };

  const runPair = async () => {
    setIsRunning(true);
    setError("");
    try {
      const response = await fetch("/api/side-by-side", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario, seed, size }),
      });
      if (!response.ok) throw new Error("Side-by-side run failed.");
      const pair = await response.json();
      const [reno, adtp] = await Promise.all([
        fetch(`/api/results/${pair.reno_result}`).then((r) => r.json()),
        fetch(`/api/results/${pair.adtp_result}`).then((r) => r.json()),
      ]);
      setSideBySide({ reno, adtp });
      await loadSavedRuns();
    } catch (e) {
      setError(e.message);
    } finally {
      setIsRunning(false);
    }
  };

  const loadPair = async () => {
    setError("");
    try {
      const [reno, adtp] = await Promise.all([
        fetch(`/api/results/${scenario}_reno_${seed}`).then((r) => { if (!r.ok) throw new Error("Saved Reno pair not found."); return r.json(); }),
        fetch(`/api/results/${scenario}_adtp_${seed}`).then((r) => { if (!r.ok) throw new Error("Saved ADTP pair not found."); return r.json(); }),
      ]);
      setSideBySide({ reno, adtp });
    } catch (e) {
      setError(e.message);
    }
  };

  const resultsByScenario = useMemo(() => {
    const grouped = {};
    savedRuns.forEach((item) => {
      if (!grouped[item.scenario]) grouped[item.scenario] = {};
      grouped[item.scenario][item.controller] = item;
    });
    return grouped;
  }, [savedRuns]);

  const content = activeTab === "howitworks" ? <HowItWorks /> :
    activeTab === "sidebyside" ? (
      <SideBySidePage pair={sideBySide} scenario={scenario} setScenario={setScenario} seed={seed} setSeed={setSeed} onRun={runPair} onLoad={loadPair} busy={isRunning} />
    ) : activeTab === "results" ? (
      <ResultsPage groups={resultsByScenario} />
    ) : (
      <ReplayPage
        meta={meta} savedRuns={savedRuns} selectedRunName={runName} onSelectRun={selectRun}
        scenario={scenario} setScenario={setScenario} controller={controller} setController={setController}
        seed={seed} setSeed={setSeed} size={size} setSize={setSize} onRunLive={startRun}
        isRunningLive={isRunning} run={run} events={events} currentTime={currentTime}
        totalDuration={totalDuration} isPlaying={isPlaying} setIsPlaying={setIsPlaying}
        speed={speed} setSpeed={setSpeed} setCurrentTime={setCurrentTime} scenarioInfo={scenarioInfo}
      />
    );

  return (
    <>
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} apiOnline={Boolean(meta)} />
      <main className="app-shell">
        <div className="topline"><div><span className="eyebrow">Reliable transport over UDP</span><h1>ADTP experiment console</h1></div><span className="seed-pill">seed {seed}</span></div>
        {error && <div className="alert">{error}</div>}
        {content}
      </main>
    </>
  );
}

function ReplayPage({ meta, ...props }) {
  const { run, events, currentTime, scenarioInfo } = props;
  const queueMax = scenarioInfo?.initial?.queue_pkts || 50;
  return (
    <div className="page-grid">
      <ControlPanel
        {...props}
        savedRuns={props.savedRuns}
        onTogglePlay={() => props.setIsPlaying((playing) => !playing)}
        onSeek={props.setCurrentTime}
      />
      <div className="run-summary">
        <ResultCard label="Throughput" value={`${formatNumber(run?.summary?.throughput_kbps, 0)} kbps`} />
        <ResultCard label="Completion" value={`${formatNumber(run?.summary?.completion_time_s, 2)} s`} tone="purple" />
        <ResultCard label="Retransmissions" value={run?.summary?.retransmissions ?? "—"} tone="orange" />
        <ResultCard label="ADTP accuracy" value={run?.summary?.accuracy == null ? "N/A" : `${formatNumber(run.summary.accuracy * 100, 1)}%`} tone="green" />
      </div>
      {!run ? <div className="glass-card empty-state">Choose a saved result to start the replay.</div> : (
        <>
          <NetworkAnimation events={events} currentTime={currentTime} queueMax={queueMax} scenario={run.meta?.scenario} />
          <ReplayCharts events={events} currentTime={currentTime} totalDuration={props.totalDuration} />
          <div className="two-column"><DecisionLog events={events} currentTime={currentTime} /><ProtocolPanel events={events} currentTime={currentTime} /></div>
          <div className="legend-note">Replay is driven directly from saved <code>RunLog</code> events. Blue sent · green ACK · orange random loss · red queue overflow · purple retransmit.</div>
        </>
      )}
    </div>
  );
}

function SideBySidePage({ pair, scenario, setScenario, seed, setSeed, onRun, onLoad, busy }) {
  return (
    <div className="page-grid">
      <div className="glass-card control-strip"><label>Scenario <select className="form-select" value={scenario} onChange={(e) => setScenario(e.target.value)}><option>clean</option><option>lossy</option><option>congested</option><option>dynamic</option></select></label><label>Seed <input className="form-input" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></label><div className="button-row"><button className="btn btn-secondary" onClick={onLoad}>Load saved pair</button><button className="btn btn-primary" onClick={onRun} disabled={busy}>{busy ? "Running..." : "Run ADTP + Reno"}</button></div></div>
      {!pair ? <div className="glass-card empty-state">Run the pair to compare both controllers on the same seed and scenario.</div> : (
        <>
          <div className="run-summary">
            <ResultCard label="ADTP throughput" value={`${formatNumber(pair.adtp.summary?.throughput_kbps, 0)} kbps`} />
            <ResultCard label="Reno throughput" value={`${formatNumber(pair.reno.summary?.throughput_kbps, 0)} kbps`} tone="purple" />
            <ResultCard label="Throughput gap" value={`${formatNumber(pair.adtp.summary?.throughput_kbps - pair.reno.summary?.throughput_kbps, 0)} kbps`} tone="green" />
          </div>
          <div className="two-column"><div><h3 className="section-title">ADTP</h3><ReplayCharts events={pair.adtp.events} totalDuration={pair.adtp.events.at(-1)?.t || 1} /></div><div><h3 className="section-title">Reno</h3><ReplayCharts events={pair.reno.events} totalDuration={pair.reno.events.at(-1)?.t || 1} /></div></div>
        </>
      )}
    </div>
  );
}

function ResultsPage({ groups }) {
  const rows = Object.entries(groups).map(([name, controllers]) => ({ name, ...controllers }));
  const chart = rows.map((row) => ({ scenario: row.name, ADTP: row.adtp?.summary?.throughput_kbps || 0, Reno: row.reno?.summary?.throughput_kbps || 0 }));
  return (
    <div className="page-grid">
      <div className="hero glass-card"><span className="eyebrow">Saved evidence</span><h2>Benchmark results</h2><p>Use this page to compare the saved seed-42 runs before opening the replay.</p></div>
      <div className="glass-card chart-card"><ResponsiveContainer width="100%" height={280}><BarChart data={chart}><CartesianGrid stroke="rgba(255,255,255,.06)" vertical={false} /><XAxis dataKey="scenario" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip /><Legend /><Bar dataKey="ADTP" fill="#06b6d4" /><Bar dataKey="Reno" fill="#a855f7" /></BarChart></ResponsiveContainer></div>
      <div className="glass-card table-wrap"><table><thead><tr><th>Scenario</th><th>Controller</th><th>Throughput</th><th>Time</th><th>Retrans</th><th>Accuracy</th></tr></thead><tbody>{rows.flatMap((row) => ["adtp", "reno"].map((controller) => { const item = row[controller]; return item ? <tr key={`${row.name}-${controller}`}><td>{row.name}</td><td><span className={`badge ${controller === "adtp" ? "badge-blue" : "badge-purple"}`}>{controller}</span></td><td>{formatNumber(item.summary?.throughput_kbps, 0)} kbps</td><td>{formatNumber(item.summary?.completion_time_s, 2)} s</td><td>{item.summary?.retransmissions ?? "—"}</td><td>{item.summary?.accuracy == null ? "N/A" : `${formatNumber(item.summary.accuracy * 100, 1)}%`}</td></tr> : null;}))}</tbody></table></div>
      <div className="glass-card confusion"><h3>ADTP confusion matrices</h3><div className="matrix-grid">{rows.map((row) => { const c = row.adtp?.summary?.confusion; return <div key={row.name}><strong>{row.name}</strong><div className="matrix"><span>said random / truth random<br /><b>{c?.random?.random ?? 0}</b></span><span>said random / queue<br /><b>{c?.random?.queue_overflow ?? 0}</b></span><span>said congestion / random<br /><b>{c?.congestion?.random ?? 0}</b></span><span>said congestion / queue<br /><b>{c?.congestion?.queue_overflow ?? 0}</b></span></div></div>; })}</div></div>
    </div>
  );
}
