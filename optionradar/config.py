"""OptionRadar configuration.

Two things live here and nowhere else:

  * UNIVERSE  -- the curated, static watchlist (spec section 1). Add / remove
                names by hand. No auto-expansion.
  * PARAMS    -- the single tuning table (spec section 10). Every magic number
                used anywhere in the pipeline is defined here so the system can
                be tuned from one place during paper trading.

Nothing in this module reaches the network or computes anything; it is pure
declaration.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Section 1 -- Universe
# --------------------------------------------------------------------------- #
# Each tradeable name maps to a sector ETF (for the F5 leadership factor).
# ETFs benchmark against SPY only. Keep this static.

@dataclass(frozen=True)
class Name:
    symbol: str
    bucket: str
    sector_etf: str


UNIVERSE: list[Name] = [
    # Technology -> XLK
    Name("NVDA", "Technology", "XLK"),
    Name("MSFT", "Technology", "XLK"),
    Name("AAPL", "Technology", "XLK"),
    Name("META", "Technology", "XLK"),
    Name("AMZN", "Technology", "XLK"),
    Name("GOOGL", "Technology", "XLK"),
    Name("TSLA", "Technology", "XLK"),
    Name("AMD", "Technology", "XLK"),
    Name("AVGO", "Technology", "XLK"),
    Name("PLTR", "Technology", "XLK"),
    # Semis -> SMH
    Name("MU", "Semis", "SMH"),
    Name("ARM", "Semis", "SMH"),
    Name("QCOM", "Semis", "SMH"),
    Name("ANET", "Semis", "SMH"),
    # Financials -> XLF
    Name("JPM", "Financials", "XLF"),
    Name("GS", "Financials", "XLF"),
    # Growth -> sector specific
    Name("NFLX", "Growth", "XLC"),
    Name("UBER", "Growth", "XLY"),
    Name("CRWD", "Growth", "IGV"),
    Name("SNOW", "Growth", "IGV"),
    # ETFs (their own sector benchmark is SPY)
    Name("QQQ", "ETFs", "SPY"),
    Name("SPY", "ETFs", "SPY"),
    Name("IWM", "ETFs", "SPY"),
    Name("SMH", "ETFs", "SPY"),
]

# The broad-market benchmark every name (and every sector ETF) is measured
# against. Also drives the section-5 market-regime check.
MARKET_BENCHMARK = "SPY"


def universe_symbols() -> list[str]:
    return [n.symbol for n in UNIVERSE]


def sector_etfs() -> list[str]:
    """Distinct sector ETFs referenced by the universe (for price fetching)."""
    return sorted({n.sector_etf for n in UNIVERSE})


def all_price_symbols() -> list[str]:
    """Every symbol whose daily candles the pipeline needs: the universe, the
    sector ETFs, and the market benchmark."""
    syms = set(universe_symbols()) | set(sector_etfs()) | {MARKET_BENCHMARK}
    return sorted(syms)


def name_for(symbol: str) -> Name | None:
    for n in UNIVERSE:
        if n.symbol == symbol:
            return n
    return None


# --------------------------------------------------------------------------- #
# Section 10 -- Parameters (the single tuning table)
# --------------------------------------------------------------------------- #
# Keep ALL magic numbers here. Adjust during paper trading by hand; do not
# backtest-tune (spec 11.4).

@dataclass(frozen=True)
class Params:
    # --- indicator periods ---
    ema_periods: tuple[int, int, int] = (20, 50, 200)
    rsi_period: int = 14
    atr_period: int = 14

    # --- minimum daily history required to evaluate a name ---
    min_history_days: int = 260

    # --- Stage 1 gates ---
    g2_rsi_cap: float = 75.0              # blow-off cap
    g2_atr_extension: float = 1.5         # (close - EMA20)/ATR limit
    g3_movement_floor: float = 0.015      # ATR/close >= 1.5% daily range
    g4_spread_max: float = 0.05           # (ask-bid)/mid <= 5% (quality; kept tight)
    # OI / day-volume floors for a single 45-60 DTE strike. Tuned down from the
    # spec's 500/50 during paper trading: far-dated single strikes trade thin,
    # and with liquidity-aware strike selection (strike.py) the chosen contract
    # is already the most tradeable in the delta band, so these are a safety net.
    g4_oi_floor: int = 250
    g4_vol_floor: int = 25
    g5_earnings_buffer_days: int = 50     # next_earnings must be > 50 days out

    # --- Stage 2 factor weights (must sum to 1.0) ---
    weights: dict[str, float] = field(default_factory=lambda: {
        "F1": 0.20,   # trend quality
        "F2": 0.22,   # IV cheapness          (half the gem)
        "F3": 0.10,   # coiled / pullback
        "F4": 0.18,   # room to run
        "F5": 0.20,   # leadership            (other half of the gem)
        "F6": 0.05,   # volume / participation
        "F7": 0.05,   # momentum
    })

    # --- F2 IV percentile lookback ---
    iv_percentile_window: int = 252

    # --- F4 room-to-run scaling: cap at this many ATR clear ---
    f4_atr_clear_cap: float = 5.0

    # --- F5 leadership lookback windows (trading days) ---
    leadership_windows: tuple[int, int] = (20, 60)

    # --- F7 momentum RSI band ---
    f7_rsi_peak_low: float = 50.0
    f7_rsi_peak_high: float = 65.0
    f7_rsi_zero_high: float = 75.0
    f7_rsi_zero_low: float = 45.0

    # --- Stage 3 Standard fire logic ---
    std_composite_min: float = 80.0
    std_core_factor_min: float = 60.0     # min(F1,F2,F4,F5) >= this
    std_core_factors: tuple[str, ...] = ("F1", "F2", "F4", "F5")
    std_confluence_count: int = 5         # at least N of 7 factors...
    std_confluence_threshold: float = 70.0  # ...>= this
    std_separation_min: float = 8.0       # composite[#1] - composite[#2]

    # --- weak-tape bumps (applied when SPY not above its 50 & 200 EMA) ---
    weak_tape_composite_min: float = 85.0
    weak_tape_separation_min: float = 12.0

    # --- Moonshot upgrade ---
    moon_composite_min: float = 92.0
    moon_all_factor_min: float = 75.0     # min(all 7) >= this
    moon_f2_min: float = 80.0             # IV pct <= ~20
    moon_f5_min: float = 85.0
    moon_f4_min: float = 85.0             # ~ >=4 ATR clear
    moon_separation_min: float = 15.0

    # --- Section 6: strike / delta / DTE ---
    std_delta_range: tuple[float, float] = (0.55, 0.70)
    moon_delta_range: tuple[float, float] = (0.45, 0.55)
    std_delta_target: float = 0.62
    moon_delta_target: float = 0.50
    dte_range: tuple[int, int] = (45, 60)
    iv_snapshot_dte_range: tuple[int, int] = (30, 45)  # ATM IV snapshot expiry

    # --- Section 7: exits ---
    std_target_pct: float = 0.27          # +27% close all
    std_stop_pct: float = -0.18           # -18% hard stop
    std_time_stop_dte: int = 21           # close if DTE < 21 with no progress
    moon_scale_out_pct: float = 0.30      # sell half at +30%
    moon_runner_target_low: float = 0.60  # +60%
    moon_runner_target_high: float = 1.00  # +100%
    moon_runner_trail_atr: float = 1.0    # trail by 1x ATR after scale-out

    # --- morning entry check (next-session re-validation, ~9:45 ET) ---
    # If the underlying gapped more than this many ATR away from the signal's
    # reference close overnight, flag it: the setup (especially "coiled near
    # EMA20") may no longer hold and you'd be entering extended.
    morning_gap_atr_warn: float = 1.0

    # --- IV-history warm-up thresholds (spec 11.3 forward-collection ladder) ---
    iv_warmup_standard_days: int = 90     # < this: caveat standard, suppress moon
    iv_warmup_full_days: int = 252        # >= this: full strength, moonshots on


PARAMS = Params()


def validate_params(p: Params = PARAMS) -> None:
    """Cheap sanity checks so a bad edit to the tuning table fails loudly."""
    total = round(sum(p.weights.values()), 6)
    if total != 1.0:
        raise ValueError(f"Factor weights must sum to 1.0, got {total}")
    for fid in ("F1", "F2", "F3", "F4", "F5", "F6", "F7"):
        if fid not in p.weights:
            raise ValueError(f"Missing weight for factor {fid}")
