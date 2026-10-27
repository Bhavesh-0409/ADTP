# ADTP Build Plan

Status key: DONE (in this zip, tested) | TODO

| # | Step | Status | Files | Done when |
|---|------|--------|-------|-----------|
| 1 | Packet encode/decode + tests | DONE | `adtp/packet.py`, `tests/test_packet.py` | all packet tests green |
| - | RTT/RTO estimator | DONE | `adtp/rtt.py` | tests green |
| - | Controllers (Reno, ADTP, Fixed) | DONE | `adtp/congestion/` | unit tests green |
| - | Metrics, JSON/CSV, accuracy fn | DONE | `adtp/metrics.py` | tests green |
| - | Scenario definitions | DONE | `adtp/scenarios.py` | tuned later (step 7) |
| 2 | Handshake + clean transfer, Fixed window | DONE | `sender.py`, `receiver.py` | file arrives, sha256 matches |
| 3 | RTO + fast retransmit in sender | DONE | `sender.py` | recovers from forced single drops |
| 4 | Reno through sender | DONE | `sender.py`, `tests/test_integration.py` | cwnd shows slow start -> CA and fast-recovery loss cut |
| 5 | Emulator + ground-truth drops | DONE | `emulator.py`, `tests/test_emulator.py` | 2 MB Reno checkpoint passed, tests green |
| 6 | ADTP classifier wired in | DONE | `sender.py`, `config.py` | ADTP beats Reno on lossy (~+26% at 500 KB-2 MB); on small-queue congested it can underperform Reno on some seeds (misclassifies congestion as random). Report as a limitation. |
| 7 | Runner + CLI results | DONE | `runner.py`, `cli.py` | `run-all` prints ADTP vs Reno table |
| 8 | FastAPI + WebSocket | DONE | `api/main.py` | saved-result, background-run, side-by-side, and event-stream endpoints |
| 9 | Dashboard | DONE | `frontend/` | replay-first dark dashboard with charts, animation, comparison, and results views |
| 10 | Report, slides, README polish | TODO | `docs/` | |

**Gate:** do not start step 9 until a file transfers correctly under Reno through the emulator (step 5).

## Integration tests to add (replace `tests/test_integration_todo.py`)
handshake, clean transfer + checksum, triple-dup-ACK retransmit, timeout retransmit,
out-of-order delivery, duplicate suppression, Reno via emulator with loss, ADTP vs Reno on the lossy scenario.

## Tuning checklist (step 7)
1. Lossy scenario: ADTP should win clearly. If not, check the classifier is seeing `recent_rtt` and `base_rtt`.
2. Sweep `ADTP_BACKLOG_THRESHOLD` (1, 2, 3, 5, 8) and plot accuracy vs throughput. That is a good report figure.
3. Congested scenario: confirm queue overflow actually happens (`drop` events labelled `queue_overflow`).
4. Run each scenario with 3+ seeds; report mean and spread, not one lucky run.
