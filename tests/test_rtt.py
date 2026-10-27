import pytest

from adtp.rtt import RttEstimator


def test_first_sample_initialises():
    r = RttEstimator()
    r.update(0.1)
    assert r.srtt == pytest.approx(0.1)
    assert r.rttvar == pytest.approx(0.05)
    assert r.rto == pytest.approx(0.1 + 4 * 0.05)   # 0.3, above the 0.2 floor
    assert r.base_rtt == pytest.approx(0.1)


def test_rto_respects_floor():
    r = RttEstimator(min_rto=0.2)
    for _ in range(50):
        r.update(0.001)
    assert r.rto == pytest.approx(0.2)


def test_base_rtt_is_minimum_and_never_rises():
    r = RttEstimator()
    for s in (0.10, 0.08, 0.15, 0.30):
        r.update(s)
    assert r.base_rtt == pytest.approx(0.08)


def test_srtt_moves_toward_new_level():
    r = RttEstimator()
    r.update(0.05)
    for _ in range(100):
        r.update(0.2)
    assert r.srtt == pytest.approx(0.2, rel=0.01)


def test_backoff_doubles_and_caps():
    r = RttEstimator(initial_rto=1.0, max_rto=3.0)
    r.backoff()
    assert r.rto == 2.0
    r.backoff()
    assert r.rto == 3.0


def test_recent_rtt_window_and_bad_samples():
    r = RttEstimator(recent_window=3)
    assert r.recent_rtt is None
    r.update(-1)
    r.update(0)
    assert r.recent_rtt is None
    for s in (0.1, 0.2, 0.3, 0.4):
        r.update(s)
    assert r.recent_rtt == pytest.approx(0.3)   # mean of 0.2, 0.3, 0.4
