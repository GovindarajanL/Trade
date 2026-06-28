from optionradar import fire
from optionradar.fire import Decision
from optionradar.models import Candidate, MarketRegime, ScoreResult
from tests.factories import make_snapshot

GOOD_REGIME = MarketRegime(spy_above_50_200=True)
WEAK_REGIME = MarketRegime(spy_above_50_200=False)


def _cand(symbol, factors, composite):
    return Candidate(snapshot=make_snapshot(symbol=symbol),
                     score=ScoreResult(factors=factors, composite=composite))


def _strong_factors():
    return {"F1": 85, "F2": 82, "F3": 75, "F4": 88, "F5": 86, "F6": 78, "F7": 80}


def test_no_candidates_is_no_trade():
    res = fire.evaluate([], GOOD_REGIME)
    assert res.decision == Decision.NO_TRADE


def test_standard_fires_with_clear_separation():
    top = _cand("AAA", _strong_factors(), 84.0)
    runner = _cand("BBB", _strong_factors(), 70.0)
    res = fire.evaluate([top, runner], GOOD_REGIME)
    assert res.decision == Decision.STANDARD


def test_separation_block_reports_runner():
    top = _cand("AAA", _strong_factors(), 84.0)
    runner = _cand("BBB", _strong_factors(), 82.0)   # only 2 apart < 8
    res = fire.evaluate([top, runner], GOOD_REGIME)
    assert res.decision == Decision.NO_TRADE
    assert "separation" in res.block_reason
    assert "BBB" in res.block_reason


def test_weak_core_factor_blocks():
    f = _strong_factors()
    f["F2"] = 55   # core factor below 60
    top = _cand("AAA", f, 84.0)
    runner = _cand("BBB", _strong_factors(), 60.0)
    res = fire.evaluate([top, runner], GOOD_REGIME)
    assert res.decision == Decision.NO_TRADE
    assert "weak core" in res.block_reason


def test_weak_tape_raises_the_bar():
    # composite 84 fires in a good tape but not in a weak one (needs >=85)
    top = _cand("AAA", _strong_factors(), 84.0)
    runner = _cand("BBB", _strong_factors(), 60.0)
    assert fire.evaluate([top, runner], GOOD_REGIME).decision == Decision.STANDARD
    assert fire.evaluate([top, runner], WEAK_REGIME).decision == Decision.NO_TRADE


def test_moonshot_upgrade():
    f = {"F1": 95, "F2": 90, "F3": 85, "F4": 90, "F5": 90, "F6": 88, "F7": 85}
    top = _cand("CRWD", f, 93.0)
    runner = _cand("BBB", _strong_factors(), 70.0)   # 23 apart > 15
    res = fire.evaluate([top, runner], GOOD_REGIME)
    assert res.decision == Decision.MOONSHOT


def test_moonshot_suppressed_during_warmup():
    f = {"F1": 95, "F2": 90, "F3": 85, "F4": 90, "F5": 90, "F6": 88, "F7": 85}
    top = _cand("CRWD", f, 93.0)
    runner = _cand("BBB", _strong_factors(), 70.0)
    res = fire.evaluate([top, runner], GOOD_REGIME, moonshots_allowed=False)
    assert res.decision == Decision.STANDARD
