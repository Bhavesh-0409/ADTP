import pytest

from adtp.congestion import (AdtpController, FixedWindowController, RenoController,
                             make_controller)

BASE = 0.05


def grown(cls, cwnd=20.0, **kw):
    c = cls(**kw)
    c.cwnd = cwnd
    c.ssthresh = 10.0   # in congestion avoidance
    return c


# ---------------- Reno ----------------
def test_reno_slow_start_adds_one_per_acked_packet():
    c = RenoController()
    c.on_ack(1, None, None)
    assert c.cwnd == 2
    c.on_ack(2, None, None)
    assert c.cwnd == 4
    assert c.phase == "slow_start"


def test_reno_congestion_avoidance_adds_about_one_per_rtt():
    c = grown(RenoController, cwnd=10.0)
    for _ in range(10):          # one window's worth of ACKs
        c.on_ack(1, None, None)
    assert 10.9 < c.cwnd < 11.1
    assert c.phase == "congestion_avoidance"


def test_reno_triple_dupack_halves_and_enters_recovery():
    c = grown(RenoController, cwnd=20.0)
    d = c.on_triple_dup_ack(BASE, BASE)
    assert c.ssthresh == 10 and c.cwnd == 13 and c.in_recovery
    assert d.classification == "unclassified" and d.trigger == "dupack"
    c.on_dup_ack()
    assert c.cwnd == 14                       # inflation
    c.on_ack(1, BASE, BASE)                   # new ACK: deflate and leave recovery
    assert c.cwnd == 10 and not c.in_recovery


def test_reno_ignores_dupack_outside_recovery():
    c = grown(RenoController, cwnd=20.0)
    c.on_dup_ack()
    assert c.cwnd == 20


def test_reno_timeout_resets_to_one_packet():
    c = grown(RenoController, cwnd=20.0)
    d = c.on_timeout(BASE, BASE)
    assert c.cwnd == 1 and c.ssthresh == 10 and not c.in_recovery
    assert d.trigger == "timeout"


def test_ssthresh_floor_is_two():
    c = RenoController()
    c.cwnd = 2.0
    c.on_triple_dup_ack(None, None)
    assert c.ssthresh == 2


# ---------------- ADTP ----------------
def test_adtp_backlog_formula():
    c = grown(AdtpController, cwnd=20.0)
    assert c.backlog(0.10, 0.05) == pytest.approx(10.0)   # 20 * 0.05 / 0.10
    assert c.backlog(0.05, 0.05) == 0
    assert c.backlog(None, 0.05) is None


def test_adtp_random_loss_small_cut():
    c = grown(AdtpController, cwnd=20.0)
    d = c.on_triple_dup_ack(rtt=BASE, base_rtt=BASE)       # RTT == base -> empty queue
    assert d.classification == "random"
    assert c.ssthresh == pytest.approx(16.0)              # 0.8 * 20
    assert c.cwnd == pytest.approx(19.0)                  # + 3 for fast recovery
    assert "RANDOM" in d.reason


def test_adtp_congestion_halves_like_reno():
    c = grown(AdtpController, cwnd=20.0)
    d = c.on_triple_dup_ack(rtt=0.10, base_rtt=BASE)       # backlog 10 >= 3
    assert d.classification == "congestion"
    assert c.ssthresh == pytest.approx(10.0) and c.cwnd == pytest.approx(13.0)


def test_adtp_threshold_boundary_and_tunable():
    # cwnd 20, backlog = 20*(r-0.05)/r ; r=0.0588 -> ~3.0
    c = grown(AdtpController, cwnd=20.0)
    assert c.on_triple_dup_ack(0.0560, BASE).classification == "random"      # ~2.14
    c = grown(AdtpController, cwnd=20.0)
    assert c.on_triple_dup_ack(0.0600, BASE).classification == "congestion"  # ~3.33
    c = grown(AdtpController, cwnd=20.0, threshold=6.0)
    assert c.on_triple_dup_ack(0.0600, BASE).classification == "random"      # same RTT, looser threshold


def test_adtp_without_rtt_data_falls_back_to_reno():
    c = grown(AdtpController, cwnd=20.0)
    d = c.on_triple_dup_ack(None, None)
    assert c.ssthresh == 10 and d.classification == "congestion" and d.backlog is None


def test_adtp_timeout_still_collapses_window_but_classifies():
    c = grown(AdtpController, cwnd=20.0, timeout_as_congestion=False)
    d = c.on_timeout(rtt=BASE, base_rtt=BASE)
    assert c.cwnd == 1 and c.ssthresh == pytest.approx(16.0) and d.classification == "random"


def test_adtp_timeout_as_congestion_flag():
    # Default is timeout_as_congestion=True
    c = grown(AdtpController, cwnd=20.0)
    d = c.on_timeout(rtt=BASE, base_rtt=BASE)
    assert c.cwnd == 1 and c.ssthresh == pytest.approx(10.0) and d.classification == "congestion"
    assert "timeout classified CONGESTION" in d.reason


def test_adtp_grows_like_reno_when_no_loss():
    a, r = AdtpController(), RenoController()
    for _ in range(30):
        a.on_ack(1, BASE, BASE)
        r.on_ack(1, BASE, BASE)
    assert a.cwnd == r.cwnd


# ---------------- Fixed + factory ----------------
def test_fixed_never_changes():
    c = FixedWindowController(window=8)
    c.on_ack(5, 0.1, 0.05)
    c.on_dup_ack()
    d1 = c.on_triple_dup_ack(0.1, 0.05)
    d2 = c.on_timeout(0.1, 0.05)
    assert c.window == 8 and d1.cwnd_after == 8 and d2.classification == "unclassified"


def test_factory():
    assert isinstance(make_controller("ADTP"), AdtpController)
    assert isinstance(make_controller("reno"), RenoController)
    assert make_controller("fixed", window=4).window == 4
    with pytest.raises(ValueError):
        make_controller("cubic")
