"""Connection state machine (shared vocabulary for sender, receiver, inspector UI).

Sender side                                  Receiver side
  CLOSED --connect()--> SYN_SENT              CLOSED --listen()--> LISTEN
  SYN_SENT --(recv SYN_ACK, send ACK)--> ESTABLISHED
                                              LISTEN --(recv SYN, send SYN_ACK)--> SYN_RCVD
                                              SYN_RCVD --(recv ACK)--> ESTABLISHED
  ESTABLISHED --(all data ACKed, send FIN)--> FIN_WAIT
  FIN_WAIT --(recv ACK of FIN)--> CLOSED      ESTABLISHED --(recv FIN, send ACK)--> CLOSED

Simplified vs TCP on purpose: one transfer per connection, one-directional data, FIN is
acknowledged by a plain ACK (ack = fin_seq + 1). SYN and FIN are retransmitted on timeout.
"""

from enum import Enum


class ConnState(str, Enum):
    CLOSED = "CLOSED"
    LISTEN = "LISTEN"
    SYN_SENT = "SYN_SENT"
    SYN_RCVD = "SYN_RCVD"
    ESTABLISHED = "ESTABLISHED"
    FIN_WAIT = "FIN_WAIT"
