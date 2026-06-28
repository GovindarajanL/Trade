"""Data layer: turn raw Schwab payloads into NameSnapshot objects.

This is the only place that reads candles and chain payloads. Everything
downstream (gates, factors, fire) is a pure function over NameSnapshot.
"""

from __future__ import annotations

from typing import Sequence

from . import indicators as ind
from .config import PARAMS, Name, Params
from .models import NameSnapshot, OptionContract


# --------------------------------------------------------------------------- #
# Option chain parsing
# --------------------------------------------------------------------------- #
def parse_chain(raw: dict) -> list[OptionContract]:
    """Flatten a Schwab CALL chain payload into OptionContract objects.

    Schwab returns callExpDateMap as {"2025-08-15:45": {"230.0": [ {...} ]}}.
    Each contract dict already carries delta, volatility, bid, ask, openInterest
    and totalVolume."""
    underlying = raw.get("symbol") or raw.get("underlying", {}).get("symbol", "")
    out: list[OptionContract] = []
    for exp_key, strikes in raw.get("callExpDateMap", {}).items():
        # exp_key looks like "2025-08-15:45" -> expiry, dte
        expiry, _, dte_str = exp_key.partition(":")
        try:
            dte = int(dte_str)
        except ValueError:
            dte = 0
        for strike_str, entries in strikes.items():
            for c in entries:
                bid = float(c.get("bid", 0) or 0)
                ask = float(c.get("ask", 0) or 0)
                mid = (bid + ask) / 2 if (bid or ask) else float(c.get("mark", 0) or 0)
                iv = c.get("volatility")
                # Schwab reports IV as a percentage (e.g. 32.5); normalise to
                # a decimal, and guard the sentinel -999.0 "not available".
                if iv in (None, -999.0):
                    iv = 0.0
                else:
                    iv = float(iv) / 100.0
                out.append(OptionContract(
                    symbol=underlying,
                    expiry=expiry,
                    dte=dte,
                    strike=float(strike_str),
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    delta=abs(float(c.get("delta", 0) or 0)),
                    iv=iv,
                    open_interest=int(c.get("openInterest", 0) or 0),
                    volume=int(c.get("totalVolume", 0) or 0),
                ))
    return out


def atm_iv_snapshot(
    contracts: Sequence[OptionContract],
    spot: float,
    p: Params = PARAMS,
) -> float | None:
    """ATM IV for the IV store = the IV of the contract nearest the money in the
    30-45 DTE expiry (spec 11.2)."""
    lo, hi = p.iv_snapshot_dte_range
    window = [c for c in contracts if lo <= c.dte <= hi and c.iv > 0]
    if not window:
        window = [c for c in contracts if c.iv > 0]
    if not window:
        return None
    nearest = min(window, key=lambda c: abs(c.strike - spot))
    return nearest.iv


# --------------------------------------------------------------------------- #
# Price-derived features
# --------------------------------------------------------------------------- #
def _range_contraction(candles, atr: float, lookback: int = 7) -> float:
    """0..1 measure of how tight recent daily ranges are vs the prior block.
    1.0 = strongly contracting (coiling), 0.0 = expanding."""
    if len(candles) < lookback * 2 or atr <= 0:
        return 0.0
    recent = candles[-lookback:]
    prior = candles[-2 * lookback:-lookback]
    recent_avg = sum(float(c["high"]) - float(c["low"]) for c in recent) / lookback
    prior_avg = sum(float(c["high"]) - float(c["low"]) for c in prior) / lookback
    if prior_avg <= 0:
        return 0.0
    ratio = recent_avg / prior_avg          # <1 means contracting
    return max(0.0, min(1.0, (1.0 - ratio) * 2.0))


def _atr_to_resistance(candles, close: float, atr: float, lookback: int = 120) -> float:
    """Distance (in ATR units) from current close up to the next ceiling: the
    highest high over the lookback window. If price is at/through it (new ATH),
    treat runway as wide open."""
    if atr <= 0:
        return 0.0
    window = candles[-lookback:] if len(candles) > lookback else candles
    highest = max(float(c["high"]) for c in window)
    if close >= highest:
        return PARAMS.f4_atr_clear_cap   # at new highs -> max runway
    return (highest - close) / atr


def _rel_strength(name_candles, bench_candles, windows) -> dict:
    out = {}
    for w in windows:
        a = ind.pct_return(name_candles, w)
        b = ind.pct_return(bench_candles, w)
        if a is not None and b is not None:
            out[w] = a - b
    return out


# --------------------------------------------------------------------------- #
# Snapshot builder
# --------------------------------------------------------------------------- #
def build_snapshot(
    name: Name,
    candles: list[dict],
    sector_candles: list[dict],
    spy_candles: list[dict],
    chain_contracts: list[OptionContract],
    iv_percentile: float | None,
    atm_iv: float | None,
    days_to_earnings: int | None,
    p: Params = PARAMS,
) -> NameSnapshot | None:
    """Returns None if there is not enough history to evaluate the name."""
    if len(candles) < p.min_history_days:
        return None

    e20, e50, e200 = p.ema_periods
    ema20 = ind.ema(ind.closes(candles), e20)[-1]
    ema50 = ind.ema(ind.closes(candles), e50)[-1]
    ema200 = ind.ema(ind.closes(candles), e200)[-1]
    ema50_series = ind.ema(ind.closes(candles), e50)
    rsi = ind.wilder_rsi(ind.closes(candles), p.rsi_period)[-1]
    atr = ind.wilder_atr(candles, p.atr_period)[-1]
    if None in (ema20, ema50, ema200, rsi, atr):
        return None

    ema50_slope_up = (
        ema50_series[-1] is not None
        and ema50_series[-6] is not None
        and ema50_series[-1] > ema50_series[-6]
    )

    close = float(candles[-1]["close"])
    volume = float(candles[-1]["volume"])
    prev_close = float(candles[-2]["close"])
    avg_vol_20 = sum(float(c["volume"]) for c in candles[-20:]) / 20

    full_stack = close > ema20 > ema50 > ema200
    dist_to_ema20_atr = (close - ema20) / atr if atr else 0.0

    rel = {
        "spy": _rel_strength(candles, spy_candles, p.leadership_windows),
        "sector": _rel_strength(candles, sector_candles, p.leadership_windows),
    }

    return NameSnapshot(
        symbol=name.symbol,
        bucket=name.bucket,
        sector_etf=name.sector_etf,
        close=close,
        volume=volume,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        ema50_slope_up=ema50_slope_up,
        rsi=rsi,
        atr=atr,
        avg_vol_20=avg_vol_20,
        up_day=close > prev_close,
        full_stack=full_stack,
        dist_to_ema20_atr=dist_to_ema20_atr,
        range_contraction=_range_contraction(candles, atr),
        atr_to_resistance=_atr_to_resistance(candles, close, atr),
        rel_strength=rel,
        iv_percentile=iv_percentile,
        days_to_earnings=days_to_earnings,
        contracts=chain_contracts,
        atm_iv=atm_iv,
    )
