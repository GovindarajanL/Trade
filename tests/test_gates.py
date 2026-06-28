from optionradar import gates
from optionradar.models import OptionContract
from tests.factories import make_contract, make_snapshot


def test_all_gates_pass_on_clean_setup():
    s = make_snapshot()
    res = gates.evaluate(s, make_contract())
    assert res.passed
    assert res.failed == []


def test_g1_fails_between_50_and_200_ema():
    # close above 200 but below 50 -> chop zone, intended failure
    s = make_snapshot(close=98.0, ema50=100.0, ema200=90.0)
    assert not gates.g1_trend_intact(s)


def test_g2_blocks_blowoff_rsi():
    s = make_snapshot(rsi=80.0)
    assert not gates.g2_not_blowoff(s)


def test_g2_blocks_vertical_extension():
    s = make_snapshot(close=120.0, ema20=105.0, atr=3.0)  # (120-105)/3 = 5 ATR
    assert not gates.g2_not_blowoff(s)


def test_g3_dead_stock_fails():
    s = make_snapshot(close=100.0, atr=1.0)   # 1% range < 1.5% floor
    assert not gates.g3_moves_enough(s)


def test_g4_wide_spread_fails():
    c = make_contract(bid=4.0, ask=6.0, mid=5.0)   # 40% spread
    assert not gates.g4_contract_tradeable(c)


def test_g4_thin_oi_fails():
    c = make_contract(open_interest=100)
    assert not gates.g4_contract_tradeable(c)


def test_g4_none_contract_fails():
    assert not gates.g4_contract_tradeable(None)


def test_g5_earnings_too_soon_fails():
    s = make_snapshot(days_to_earnings=20)
    assert not gates.g5_earnings_clear(s)


def test_g5_unknown_earnings_is_clear():
    s = make_snapshot(days_to_earnings=None)
    assert gates.g5_earnings_clear(s)
