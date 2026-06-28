"""Helpers to build NameSnapshot / OptionContract objects for tests."""

from optionradar.models import NameSnapshot, OptionContract


def make_contract(**kw) -> OptionContract:
    defaults = dict(
        symbol="TEST", expiry="2025-09-19", dte=50, strike=100.0,
        bid=4.9, ask=5.1, mid=5.0, delta=0.62, iv=0.30,
        open_interest=1000, volume=200,
    )
    defaults.update(kw)
    return OptionContract(**defaults)


def make_snapshot(**kw) -> NameSnapshot:
    defaults = dict(
        symbol="TEST", bucket="Technology", sector_etf="XLK",
        # close sits 0.5 ATR above EMA20 -> passes G2 (extension < 1.5 ATR)
        close=106.5, volume=30_000_000,
        ema20=105.0, ema50=100.0, ema200=90.0, ema50_slope_up=True,
        rsi=58.0, atr=3.0, avg_vol_20=20_000_000, up_day=True,
        full_stack=True, dist_to_ema20_atr=0.5, range_contraction=0.6,
        atr_to_resistance=5.0,
        rel_strength={"spy": {20: 0.05, 60: 0.06}, "sector": {20: 0.04, 60: 0.05}},
        iv_percentile=10.0, days_to_earnings=80,
        contracts=[make_contract()], atm_iv=0.30,
    )
    defaults.update(kw)
    return NameSnapshot(**defaults)
