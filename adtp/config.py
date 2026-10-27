"""Central constants. Everything tunable lives here so experiments are easy to repeat."""

# --- Packet / window units -------------------------------------------------
MSS = 1000                 # payload bytes per DATA packet (fixed)
RECV_WINDOW = 64           # receiver's advertised window, in packets
DUP_ACK_THRESHOLD = 3      # triple duplicate ACK -> fast retransmit

# --- Congestion control ----------------------------------------------------
INITIAL_CWND = 1.0         # packets
INITIAL_SSTHRESH = 64.0    # packets

# --- ADTP classifier (Veno-style) ------------------------------------------
# backlog N = cwnd * (RTT - baseRTT) / RTT   (estimated packets queued in the network)
ADTP_BACKLOG_THRESHOLD = 3.0   # N < threshold -> "random" loss, else "congestion"
ADTP_RANDOM_CUT = 0.8          # random loss: ssthresh = cwnd * 4/5  (Veno)
RENO_CUT = 0.5                 # congestion loss: ssthresh = cwnd / 2
ADTP_TIMEOUT_AS_CONGESTION = True  # treat timeouts as congestion loss

# --- RTT / RTO (RFC 6298 style) --------------------------------------------
RTO_INITIAL = 1.0          # seconds
RTO_MIN = 0.2              # seconds (kept low: our emulated links have tens of ms RTT)
RTO_MAX = 10.0             # seconds
RTT_RECENT_WINDOW = 4      # classifier uses mean of the last N RTT samples
