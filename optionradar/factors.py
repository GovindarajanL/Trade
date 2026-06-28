"""Stage 2 -- Scored factors (spec section 4).

Survivors only. Each factor outputs 0-100. The composite is a weighted sum used
for *ranking only*; the fire decision (section 5) uses the floor across factors,
not the composite.

The headline discriminator is the contradiction between F2 (cheap IV) and F5
(leading) -- cheap like the market forgot it, leading like it didn't. Those
rarely co-occur; when they do, that's the gem.

Note: option premium is execution-only and is deliberately *never* scored
(spec section 4 / 11.4 #3).
"""

from __future__ import annotations

from .config import PARAMS, Params
from .models import NameSnapshot, ScoreResult


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def f1_trend_quality(s: NameSnapshot) -> float:
    """Full stack (close>EMA20>EMA50>EMA200) + positive EMA50 slope.
    Perfect stack & rising = 100; partial stack scales down."""
    # Count how many of the four stack inequalities hold.
    ladder = [
        s.close > s.ema20,
        s.ema20 > s.ema50,
        s.ema50 > s.ema200,
        s.close > s.ema200,
    ]
    stack_score = sum(ladder) / len(ladder)        # 0..1
    slope_bonus = 1.0 if s.ema50_slope_up else 0.6
    return _clamp(100.0 * stack_score * slope_bonus)


def f2_iv_cheapness(s: NameSnapshot) -> float:
    """100 - IV percentile. Low IV pct = cheap optionality = high score.
    Half the gem. Returns 0 when no IV history exists (cannot claim cheap)."""
    if s.iv_percentile is None:
        return 0.0
    return _clamp(100.0 - s.iv_percentile)


def f3_coiled_pullback(s: NameSnapshot, p: Params = PARAMS) -> float:
    """Reward resting near EMA20 from above + range/ATR contraction over the
    last 5-10 bars. Penalize extension above EMA20. Peaks when price is within
    ~0.5 ATR of EMA20 and range is tightening."""
    dist = s.dist_to_ema20_atr        # signed, in ATR units
    # Proximity: peak at 0.5 ATR above EMA20, decaying as price extends.
    # Negative dist (below EMA20) is fine but trend gate already guards context.
    proximity = _clamp(100.0 * (1.0 - abs(dist - 0.5) / 2.0))
    # Extension penalty: being well above EMA20 is the opposite of coiled.
    if dist > 1.5:
        proximity *= 0.4
    # Contraction is 0..1 (1 = maximally tightening).
    contraction = _clamp(100.0 * s.range_contraction)
    return _clamp(0.6 * proximity + 0.4 * contraction)


def f4_room_to_run(s: NameSnapshot, p: Params = PARAMS) -> float:
    """Distance to next resistance (prior swing high / recent ATH) in ATR units.
    min(dist_in_ATR / cap, 1) * 100. >= cap ATR clear = 100."""
    return _clamp(min(s.atr_to_resistance / p.f4_atr_clear_cap, 1.0) * 100.0)


def f5_leadership(s: NameSnapshot) -> float:
    """Return vs SPY and vs sector ETF over 20d & 60d. Outperforming both on
    both windows = high; lagging either pulls it down. Other half of the gem."""
    spy = s.rel_strength.get("spy", {})
    sector = s.rel_strength.get("sector", {})
    deltas = []
    for win in (20, 60):
        if win in spy:
            deltas.append(spy[win])
        if win in sector:
            deltas.append(sector[win])
    if not deltas:
        return 0.0
    # Map relative outperformance to a score. A +5% edge per comparison is
    # strong leadership; lagging on any single comparison drags the floor.
    scores = [_clamp(50.0 + (d / 0.05) * 25.0) for d in deltas]
    # Use a blend that is dominated by the weakest comparison ("lagging either
    # pulls it down") while still rewarding broad strength.
    worst = min(scores)
    avg = sum(scores) / len(scores)
    return _clamp(0.6 * worst + 0.4 * avg)


def f6_volume_participation(s: NameSnapshot) -> float:
    """today_vol / 20d_avg_vol. 1.5x with an up-day = high."""
    if s.avg_vol_20 <= 0:
        return 0.0
    ratio = s.volume / s.avg_vol_20
    base = _clamp((ratio / 1.5) * 80.0)   # 1.5x -> 80 before the up-day bonus
    if s.up_day:
        base = _clamp(base + 20.0)
    else:
        base *= 0.5                       # volume without an up-day is ambiguous
    return _clamp(base)


def f7_momentum(s: NameSnapshot, p: Params = PARAMS) -> float:
    """RSI band: peak across 50-65, taper to 0 by 75 (gate cap) and below 45."""
    r = s.rsi
    lo, hi = p.f7_rsi_peak_low, p.f7_rsi_peak_high
    if lo <= r <= hi:
        return 100.0
    if r > hi:
        # taper to 0 at f7_rsi_zero_high
        span = p.f7_rsi_zero_high - hi
        return _clamp(100.0 * (1.0 - (r - hi) / span)) if span > 0 else 0.0
    # r < lo: taper to 0 at f7_rsi_zero_low
    span = lo - p.f7_rsi_zero_low
    return _clamp(100.0 * (1.0 - (lo - r) / span)) if span > 0 else 0.0


FACTOR_FNS = {
    "F1": f1_trend_quality,
    "F2": f2_iv_cheapness,
    "F3": f3_coiled_pullback,
    "F4": f4_room_to_run,
    "F5": f5_leadership,
    "F6": f6_volume_participation,
    "F7": f7_momentum,
}


def score(s: NameSnapshot, p: Params = PARAMS) -> ScoreResult:
    factors = {fid: round(fn(s), 1) for fid, fn in FACTOR_FNS.items()}
    composite = sum(factors[fid] * p.weights[fid] for fid in factors)
    return ScoreResult(factors=factors, composite=round(composite, 1))
