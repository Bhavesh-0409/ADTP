# Instructions for coding agents (Claude Code etc.)

Read `docs/DESIGN.md` and `BUILD_PLAN.md` first.

## Project
ADTP: reliable transport over UDP (Python asyncio) whose congestion controller classifies loss as
random vs congestion using RTT (TCP Veno style), compared against Reno. 2-person college Computer
Networks project. The professor cares about the networking idea. The student is NOT strong on
networking, so explain key decisions in a line or two in code comments and in your replies.

## Rules
- Follow the build order in `BUILD_PLAN.md`. Test each step before the next. No dashboard until Reno transfers correctly through the emulator.
- Do not change scope or the core idea without asking. This is Veno-style, NOT a novel invention. Never claim novelty in code, docs or slides.
- Sender talks to controllers only through `CongestionController`. Never branch on controller name inside the sender.
- Units: packets for seq/ack/window. Fixed MSS. Cumulative ACKs only, no SACK.
- Every loss event must log `seq`, `trigger`, `classification`, `backlog`, `cwnd_before/after`, `reason`.
- Every emulator drop must log `seq` and ground-truth `label` (`random` | `queue_overflow`).
- Seeded RNG everywhere. Runs must be repeatable.
- Honest results: if ADTP does not win somewhere, report it. Tune the threshold before suspecting the idea.
- Keep tests green (`python -m pytest -q`). Do not delete tests to make things pass.
- Keep responses concise and neatly structured.

## Already built and tested (do not rewrite, extend)
`packet.py`, `rtt.py`, `congestion/*`, `metrics.py`, `scenarios.py`, `connection.py`, `config.py`.

## Stubs with full contracts in their docstrings
`sender.py`, `receiver.py`, `emulator.py`, `runner.py`, `api/main.py`, `frontend/`.
