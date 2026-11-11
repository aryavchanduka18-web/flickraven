from pipeline.compare_feedback_retrain import verdict


def res(mean, lo, hi):
    return {"ranking": {"hybrid_balanced": {"ndcg": {"mean": mean, "ci_low": lo, "ci_high": hi}}}}


def test_drop_blocks_shipping():
    ok, text, _ = verdict(res(0.163, 0.155, 0.171), res(0.150, 0.142, 0.158))
    assert not ok and "Keep the old models" in text


def test_tiny_change_is_not_called_an_improvement():
    ok, text, _ = verdict(res(0.163, 0.155, 0.171), res(0.165, 0.157, 0.173))
    assert ok and "no measurable change" in text


def test_clear_rise_is_reported():
    ok, text, _ = verdict(res(0.150, 0.148, 0.152), res(0.170, 0.168, 0.172))
    assert ok and "Safe to ship." in text


def test_missing_hybrid_keeps_old_models():
    ok, _, _ = verdict({"ranking": {}}, res(0.1, 0.1, 0.1))
    assert not ok
