from optionradar import factors
from optionradar.config import validate_params
from tests.factories import make_snapshot


def test_weights_sum_to_one():
    validate_params()  # raises if not


def test_all_factors_bounded_0_100():
    s = make_snapshot()
    res = factors.score(s)
    assert set(res.factors) == {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
    assert all(0.0 <= v <= 100.0 for v in res.factors.values())
    assert 0.0 <= res.composite <= 100.0


def test_f2_iv_cheapness_inverts_percentile():
    cheap = make_snapshot(iv_percentile=5.0)
    rich = make_snapshot(iv_percentile=95.0)
    assert factors.f2_iv_cheapness(cheap) > factors.f2_iv_cheapness(rich)


def test_f2_no_history_scores_zero():
    s = make_snapshot(iv_percentile=None)
    assert factors.f2_iv_cheapness(s) == 0.0


def test_f4_room_caps_at_100():
    s = make_snapshot(atr_to_resistance=10.0)   # >5 ATR clear
    assert factors.f4_room_to_run(s) == 100.0


def test_f5_lagging_pulls_down():
    leader = make_snapshot(rel_strength={"spy": {20: 0.06, 60: 0.06},
                                         "sector": {20: 0.06, 60: 0.06}})
    laggard = make_snapshot(rel_strength={"spy": {20: -0.05, 60: 0.06},
                                          "sector": {20: 0.06, 60: 0.06}})
    assert factors.f5_leadership(leader) > factors.f5_leadership(laggard)


def test_f7_momentum_peaks_in_band():
    assert factors.f7_momentum(make_snapshot(rsi=58)) == 100.0
    assert factors.f7_momentum(make_snapshot(rsi=74)) < 100.0
    assert factors.f7_momentum(make_snapshot(rsi=44)) < 100.0
