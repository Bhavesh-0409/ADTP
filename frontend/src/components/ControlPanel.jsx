import React from "react";

export default function ControlPanel({
  savedRuns = [],
  selectedRunName = "",
  onSelectRun = () => {},
  scenario = "lossy",
  setScenario = () => {},
  controller = "adtp",
  setController = () => {},
  seed = 42,
  setSeed = () => {},
  size = 500000,
  setSize = () => {},
  onRunLive = () => {},
  isRunningLive = false,
  isPlaying = false,
  onTogglePlay = () => {},
  currentTime = 0,
  totalDuration = 10,
  onSeek = () => {},
  speed = 1,
  setSpeed = () => {},
}) {
  return (
    <div className="glass-card control-panel">
      {/* Top Row: Run selection & Controls */}
      <div className="control-row">
        {/* Load saved run picker */}
        <label className="control-field">Replay
          <select
            className="form-select"
            value={selectedRunName}
            onChange={(e) => onSelectRun(e.target.value)}
            style={{ minWidth: "220px" }}
          >
            {savedRuns.length === 0 && <option value="">No saved runs found</option>}
            {savedRuns.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name} ({r.summary?.throughput_kbps ? `${r.summary.throughput_kbps} kbps` : ""})
              </option>
            ))}
          </select>
        </label>

        {/* Live Run Launcher */}
        <div className="control-actions">
          <select className="form-select" value={scenario} onChange={(e) => setScenario(e.target.value)}>
            <option value="clean">clean</option>
            <option value="lossy">lossy</option>
            <option value="congested">congested</option>
            <option value="dynamic">dynamic</option>
          </select>

          <div className="segmented"><button className={controller === "adtp" ? "selected" : ""} onClick={() => setController("adtp")}>ADTP</button><button className={controller === "reno" ? "selected" : ""} onClick={() => setController("reno")}>Reno</button></div>

          <input
            className="form-input"
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
            aria-label="Seed"
            style={{ width: "78px" }}
          />
          <input
            className="form-input"
            type="number"
            min="1000"
            step="1000"
            value={size}
            onChange={(e) => setSize(Number(e.target.value))}
            aria-label="Transfer size in bytes"
            style={{ width: "112px" }}
          />

          <button
            className="btn btn-primary"
            onClick={onRunLive}
            disabled={isRunningLive}
          >
            {isRunningLive ? "Running..." : "Run"}
          </button>
        </div>
      </div>

      {/* Bottom Row: Playback Scrub Bar & Controls */}
      <div className="playback-bar">
        {/* Play/Pause Button */}
        <button
          className="btn btn-primary"
          onClick={onTogglePlay}
          style={{ minWidth: "112px" }}
        >
          {isPlaying ? "⏸ Pause" : "▶ Play"}
        </button>

        {/* Timeline Scrubber */}
        <div className="timeline">
          <span className="time-label">
            {currentTime.toFixed(2)}s
          </span>
          <input
            type="range"
            min="0"
            max={Math.max(0.1, totalDuration)}
            step="0.02"
            value={currentTime}
            onChange={(e) => onSeek(Number(e.target.value))}
            className="timeline-input"
          />
          <span className="time-label muted">
            {totalDuration.toFixed(2)}s
          </span>
        </div>

        {/* Playback Speed selector */}
        <div className="speed-chips">
          {[1, 4, 10].map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={speed === s ? "selected" : ""}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
