# ADTP Design

## 1. The problem
TCP Reno assumes every loss = congestion and halves its window. On Wi-Fi / mobile links, many losses are
random (noise, interference), so Reno throttles itself for no reason and wastes bandwidth.

## 2. The idea (not novel; honest framing)
Tell the two kinds of loss apart using RTT, in the style of **TCP Veno** (related: **TCP Westwood**).
- A filling queue raises RTT above the path's base RTT. Random loss does not touch the queue.
- At a loss: `N = cwnd * (RTT - baseRTT) / RTT` = estimated packets sitting in queues.
  - `N < 3` -> **random** loss -> retransmit, cut window only to 4/5.
  - `N >= 3` -> **congestion** -> halve window (Reno).
- Threshold is tunable (`config.ADTP_BACKLOG_THRESHOLD`).
- Contribution of this project: implement it on our own UDP transport, build an emulator with
  ground-truth drop labels, and measure classification accuracy and throughput honestly.

## 3. Architecture
```
 file --> [Sender] --UDP--> [Emulator] --UDP--> [Receiver] --> file (sha256 check)
            |  ^   <--UDP--  (delay, loss,   <--UDP--
            |  |             bandwidth, queue)
   Controller (Reno | ADTP | Fixed)         ground-truth drop labels
            |                                   |
            +--------> RunLog (events) <--------+
                          |
              JSON/CSV  +  FastAPI/WebSocket --> React dashboard
```

## 4. Packet format (33-byte header, network byte order)
| Field | Bytes | Purpose |
|-------|-------|---------|
| type | 1 | SYN, SYN_ACK, ACK, DATA, FIN |
| seq | 4 | packet number (packets, not bytes) |
| ack | 4 | cumulative: next packet expected |
| window | 2 | receiver's free buffer (flow control), packets |
| ts | 8 | sender clock at send, microseconds |
| ts_echo | 8 | echoed ts of the packet being ACKed -> RTT sample |
| length | 2 | payload bytes |
| checksum | 4 | CRC32 over header (checksum zeroed) + payload |

## 5. State machine
```
Sender:   CLOSED -> SYN_SENT -> ESTABLISHED -> FIN_WAIT -> CLOSED
Receiver: CLOSED -> LISTEN -> SYN_RCVD -> ESTABLISHED -> CLOSED
Handshake: SYN -> SYN_ACK -> ACK.   Teardown: FIN -> ACK(fin_seq+1).
```
Congestion phases (inside ESTABLISHED): slow start -> congestion avoidance -> fast recovery (on 3 dup-ACKs);
timeout -> cwnd=1, back to slow start.

## 6. Key decisions and why (short, for the viva)
| Decision | Reason |
|----------|--------|
| Packets as unit for seq/window | Simpler maths, same behaviour; no byte-stream bookkeeping |
| Cumulative ACKs, no SACK | Simpler; matches classic Reno. Duplicate ACKs signal a gap |
| Triple dup-ACK + RTO | Dup-ACKs detect a single loss fast; RTO is the safety net when ACKs stop |
| Karn's rule | An ACK for a retransmitted packet is ambiguous, so skip it for RTT |
| ts echoed in ACK | RTT sample on every ACK without per-packet timers |
| Base RTT = lifetime minimum | Best estimate of empty-queue RTT. Weakness: stale if path delay rises permanently |
| Classifier uses mean of last 4 RTTs | One sample is noisy; SRTT lags. Short mean is a compromise |
| Timeout still sets cwnd=1 in ADTP | A timeout means the pipe drained; only dup-ACK losses get the mild cut |
| No RTT yet -> act like Reno | Safe default |
| Own UDP emulator, bottleneck = serialization delay + drop-tail queue | Cross-platform, and queue overflow gives clean ground truth |
| ACKs also traverse the emulator | Realistic RTT; ACK delay counts in RTT |
| Plain Reno, not NewReno | Same for both controllers, keeps comparison fair. Mention as limitation |

## 7. Dashboard (build last)
Control panel (controller, scenario, live sliders) | network animation (packets coloured: sent / ACKed /
random loss / congestion loss / retransmit) | charts: cwnd, RTT + base RTT line, throughput, cumulative
retransmissions | decision log | side-by-side ADTP vs Reno | protocol inspector | results page
(tables, bar charts per scenario, classification accuracy + confusion matrix).

Event names are defined in `adtp/metrics.py`; the dashboard should only consume those.

## 8. Expected results (report whatever you actually get)
Lossy link: ADTP clearly better. Clean and congested: roughly equal. Classifier accuracy will be imperfect
because RTT is noisy; show the confusion matrix. Include threshold sweep.

## 9. Limitations to state in the report
Single flow focus, no SACK, plain Reno, emulator not real Wi-Fi, stale base RTT on permanent delay changes,
small number of seeds.
