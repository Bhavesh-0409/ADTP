from adtp.metrics import RunLog, classification_accuracy, summarize
from adtp.scenarios import SCENARIOS


def test_runlog_json_csv_roundtrip(tmp_path):
    log = RunLog(meta={"controller": "adtp"})
    log.add("cwnd", t=0.1, cwnd=2.0)
    log.add("loss", t=0.5, seq=3, classification="random")
    seen = []
    log.listeners.append(seen.append)
    log.add("rtt", t=0.6, rtt=0.05)
    assert len(seen) == 1

    j = log.save_json(tmp_path / "r.json")
    back = RunLog.load_json(j)
    assert back.meta["controller"] == "adtp" and len(back.events) == 3
    assert len(back.of_kind("loss")) == 1

    c = log.save_csv(tmp_path / "r.csv")
    header = c.read_text().splitlines()[0].split(",")
    assert {"t", "kind", "cwnd", "seq", "classification", "rtt"} <= set(header)


def test_summarize():
    s = summarize(completion_time=2.0, file_bytes=1_000_000, rtt_samples=[0.04, 0.06],
                  retransmissions=5, packets_sent=1005)
    assert s["throughput_kbps"] == 4000.0 and s["avg_rtt_ms"] == 50.0 and s["retransmissions"] == 5


def test_classification_accuracy_confusion_and_unmatched():
    drops = [
        {"t": 1.0, "seq": 10, "label": "random"},
        {"t": 2.0, "seq": 20, "label": "queue_overflow"},
        {"t": 3.0, "seq": 30, "label": "random"},
        {"t": 4.0, "seq": 40, "label": "queue_overflow"},
    ]
    decisions = [
        {"t": 1.1, "seq": 10, "classification": "random"},        # correct
        {"t": 2.1, "seq": 20, "classification": "congestion"},    # correct
        {"t": 3.1, "seq": 30, "classification": "congestion"},    # wrong
        {"t": 4.1, "seq": 40, "classification": "random"},        # wrong
        {"t": 5.0, "seq": 99, "classification": "random"},        # no drop -> unmatched
        {"t": 6.0, "seq": 10, "classification": "unclassified"},  # Reno-style, ignored
    ]
    r = classification_accuracy(decisions, drops)
    assert r["accuracy"] == 0.5 and r["matched"] == 4 and r["unmatched"] == 1
    assert r["confusion"]["random"] == {"random": 1, "queue_overflow": 1}
    assert r["confusion"]["congestion"] == {"random": 1, "queue_overflow": 1}


def test_accuracy_uses_latest_drop_before_decision():
    drops = [{"t": 1.0, "seq": 7, "label": "random"}, {"t": 2.0, "seq": 7, "label": "queue_overflow"}]
    r = classification_accuracy([{"t": 2.5, "seq": 7, "classification": "congestion"}], drops)
    assert r["accuracy"] == 1.0
    assert classification_accuracy([], [])["accuracy"] is None


def test_scenarios_are_well_formed():
    assert {"clean", "lossy", "congested", "dynamic"} <= set(SCENARIOS)
    assert SCENARIOS["lossy"].initial.loss_pct > 0 and SCENARIOS["congested"].initial.loss_pct == 0
    assert SCENARIOS["dynamic"].changes[0][1] == {"loss_pct": 5.0}
