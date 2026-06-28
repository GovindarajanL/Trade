"""Plain data containers passed between pipeline stages.

These deliberately hold *derived* values so that gates / factors / fire logic
never re-touch raw candles or the network. The data layer (data.py) builds
these; everything downstream is pure functions over them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OptionContract:
    """A single call contract from the Schwab chain payload."""
    symbol: str            # underlying
    expiry: str            # ISO date
    dte: int
    strike: float
    bid: float
    ask: float
    mid: float
    delta: float
    iv: float              # decimal, e.g. 0.32
    open_interest: int
    volume: int            # day volume

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return 1.0
        return (self.ask - self.bid) / self.mid


@dataclass
class NameSnapshot:
    """Everything the pipeline needs about one universe name, for one day."""
    symbol: str
    bucket: str
    sector_etf: str

    # latest bar
    close: float
    volume: float

    # indicators (latest values)
    ema20: float
    ema50: float
    ema200: float
    ema50_slope_up: bool
    rsi: float
    atr: float
    avg_vol_20: float
    up_day: bool

    # trend-stack flags
    full_stack: bool       # close>EMA20>EMA50>EMA200

    # pullback / coil inputs
    dist_to_ema20_atr: float    # (close - EMA20) / ATR, signed
    range_contraction: float    # 0..1, recent range vs prior range

    # room to run
    atr_to_resistance: float    # distance to next ceiling, in ATR units

    # leadership: return deltas vs SPY and sector, per window
    rel_strength: dict          # {"spy": {20:..,60:..}, "sector": {20:..,60:..}}

    # IV percentile (0..100) computed against the IV store; None if no history
    iv_percentile: float | None

    # earnings
    days_to_earnings: int | None

    # option chain for the standard / moonshot expiries
    contracts: list[OptionContract] = field(default_factory=list)

    # IV value snapshotted into the store this run (ATM, 30-45 DTE)
    atm_iv: float | None = None


@dataclass
class GateResult:
    passed: bool
    gates: dict          # {"G1": True, "G2": False, ...}
    failed: list         # ["G2", ...]


@dataclass
class ScoreResult:
    factors: dict        # {"F1": 84.0, ...}
    composite: float
    rank: int = 0


@dataclass
class Candidate:
    snapshot: NameSnapshot
    score: ScoreResult


@dataclass
class MarketRegime:
    spy_above_50_200: bool   # SPY close above its own 50 & 200 EMA
