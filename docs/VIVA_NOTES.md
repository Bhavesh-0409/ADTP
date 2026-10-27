# Viva cheat sheet: networking concepts in plain words

## Core terms
- **Congestion window (cwnd):** how many packets the sender may have un-ACKed in the network. Sender's self-limit.
- **Receiver window (flow control):** how much the receiver can buffer. Sender uses `min(cwnd, rwnd)`.
- **ssthresh:** the cwnd value where growth switches from fast (slow start) to gentle (congestion avoidance).
- **Slow start:** cwnd doubles per RTT. "Slow" only compared to sending everything at once.
- **Congestion avoidance:** cwnd grows by about 1 per RTT.
- **Fast retransmit:** 3 duplicate ACKs = a packet was lost but later ones arrived; resend now without waiting.
- **Fast recovery:** after fast retransmit keep sending (window inflated) instead of restarting from 1.
- **RTO:** timer for when ACKs stop entirely. `SRTT + 4*RTTVAR`. Doubles on each timeout (backoff).
- **RTT / base RTT:** round trip time / smallest RTT seen (roughly empty-network RTT).
- **Queueing delay:** `RTT - base RTT`. Grows as the router queue fills.
- **Drop-tail queue:** when full, new packets are dropped.
- **Bandwidth-delay product:** bandwidth x RTT = packets needed in flight to fill the link.

## Likely questions
1. **Why does Reno do badly on Wi-Fi?** It halves on every loss even when the loss was random noise, so the link stays under-used.
2. **How does ADTP tell them apart?** Queue building raises RTT above base RTT; random loss leaves RTT near base. Backlog `N = cwnd*(RTT-base)/RTT`, threshold 3 packets.
3. **Is this new?** No. It follows TCP Veno; Westwood is related. Our work is implementing and measuring it on our own transport.
4. **What if the classifier is wrong?** Wrongly "random" -> too gentle on real congestion (slightly more loss). Wrongly "congestion" -> behaves like Reno. So failure degrades to Reno-like, not worse.
5. **Why UDP?** Lets us build transport logic in user space; TCP's kernel stack cannot be changed.
6. **Why cumulative ACKs?** Simplicity; duplicate ACKs naturally signal a gap.
7. **Why does slow start double?** +1 per ACKed packet, and a window of N packets yields N ACKs per RTT.
8. **How do you know the emulator's drops are labelled correctly?** Random drop is decided before the queue; queue drop happens only when the queue is full. Label is attached at the drop site.
9. **Why might ADTP not beat Reno on the congested link?** All losses there are real congestion, so correct classification = Reno behaviour. Equal is the right result.
10. **Limitations?** See DESIGN.md section 9.
