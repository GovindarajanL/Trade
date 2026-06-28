"""Technical indicators, computed in pure Python over candle lists.

A "candle" is a dict with at least the keys: date, open, high, low, close,
volume. Candles are always ordered oldest -> newest. No third-party numeric
dependency is needed at this scale (a few hundred bars per name).

All functions that return a series return a list aligned 1:1 with the input
candles, using None for leading positions that cannot yet be computed.
"""

from __future__ import annotations

from typing import Sequence

Candle = dict


def closes(candles: Sequence[Candle]) -> list[float]:
    return [float(c["close"]) for c in candles]


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Exponential moving average. Seeded with the SMA of the first `period`
    values (standard convention)."""
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def wilder_rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    """RSI using Wilder's smoothing."""
    n = len(values)
    out: list[float | None] = [None] * n
    if n <= period:
        return out

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period

    def rsi_from(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, n):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = rsi_from(avg_gain, avg_loss)
    return out


def true_ranges(candles: Sequence[Candle]) -> list[float | None]:
    out: list[float | None] = [None] * len(candles)
    for i in range(1, len(candles)):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        prev_close = float(candles[i - 1]["close"])
        out[i] = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
    return out


def wilder_atr(candles: Sequence[Candle], period: int = 14) -> list[float | None]:
    """Average True Range using Wilder's smoothing."""
    n = len(candles)
    out: list[float | None] = [None] * n
    tr = true_ranges(candles)
    # first `period` true ranges occupy indices 1..period
    if n <= period:
        return out
    first = [t for t in tr[1:period + 1] if t is not None]
    if len(first) < period:
        return out
    atr = sum(first) / period
    out[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + tr[i]) / period
        out[i] = atr
    return out


def pct_return(candles: Sequence[Candle], lookback: int) -> float | None:
    """Simple close-to-close percent return over `lookback` trading days."""
    if len(candles) <= lookback:
        return None
    now = float(candles[-1]["close"])
    then = float(candles[-1 - lookback]["close"])
    if then == 0:
        return None
    return (now / then) - 1.0


def realized_vol(candles: Sequence[Candle], window: int = 20) -> float | None:
    """Annualized realized volatility from daily log returns -- used only as a
    cheap IV proxy seed (spec 11.3 fallback ladder), never for scoring."""
    import math

    if len(candles) <= window:
        return None
    rets = []
    cs = closes(candles[-(window + 1):])
    for i in range(1, len(cs)):
        if cs[i - 1] > 0 and cs[i] > 0:
            rets.append(math.log(cs[i] / cs[i - 1]))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)
