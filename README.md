# ADTP: Adaptive Data Transport Protocol

Reliable transport over UDP (Python asyncio) with a TCP-Veno-style congestion controller that separates
**random loss** from **congestion** using RTT, compared against a Reno baseline on an emulated network.
Computer Networks course project. The idea follows TCP Veno / Westwood; it is not claimed as novel.

## Status
Protocol, runner, API, and replay-first dashboard are implemented. See `BUILD_PLAN.md`
for the remaining report/slides polish.

## Quick start
```bash
pip install -r requirements.txt
python -m pytest -q          # 44 pass, 8 integration placeholders skipped
python -m adtp.cli info      # controllers, scenarios, config
```
Dashboard demo (run these commands in order):
```bash
python scripts/make_demo_data.py
uvicorn api.main:app --port 8000
# In a second terminal:
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The demo-data script creates the saved seed-42
replays for clean, lossy, congested, and dynamic scenarios, then refreshes the
lossy and dynamic ADTP/Reno pairs. The dashboard loads replay data first; live
runs are optional from the same control panel.

## Layout
```
adtp/            protocol package
  packet.py        header, encode/decode, checksum        (done)
  rtt.py           SRTT/RTTVAR/RTO + base RTT             (done)
  congestion/      Reno, ADTP, Fixed controllers          (done)
  metrics.py       RunLog, JSON/CSV, classification acc.  (done)
  scenarios.py     scenario definitions                   (done)
  connection.py    state names + diagram                  (done)
  sender.py receiver.py emulator.py runner.py             (stubs with contracts)
api/             FastAPI + WebSocket dashboard API
frontend/        React + Vite replay-first dashboard
tests/           unit tests + integration placeholders
docs/            DESIGN.md, VIVA_NOTES.md
results/ data/   run outputs and test files
```

## Docs
`docs/DESIGN.md` (architecture, packet format, decisions) | `docs/VIVA_NOTES.md` | `CLAUDE.md` (for coding agents)
