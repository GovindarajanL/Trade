"""Strike / delta / DTE selection (spec section 6) and exit-plan construction
(section 7).

Standard:  delta 0.55-0.70 (ATM -> slightly ITM), DTE 45-60.
Moonshot:  delta 0.45-0.55 (slightly OTM, more convexity), DTE 45-60.

Pick the strike on the chain that lands closest to the target delta within the
allowed DTE window, then the caller re-checks G4 liquidity on that exact strike
before emitting (chain liquidity drifts -- spec 11.4 #1).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import gates
from .config import PARAMS, Params
from .fire import Decision
from .models import NameSnapshot, OptionContract


def select_contract(
    s: NameSnapshot,
    decision: Decision,
    p: Params = PARAMS,
    enforce_volume: bool = True,
) -> OptionContract | None:
    """Pick the contract to trade for the tier.

    Liquidity-aware: among the calls in the DTE window AND the delta band, prefer
    one that actually clears the liquidity gate (G4), and of those take the one
    nearest the target delta. This keeps us off dead far-dated strikes that merely
    happen to match the delta but can't be filled or exited at a fair price -- the
    failure mode seen in paper trading, where the picker landed on 60-DTE strikes
    with zero volume.

    Fallbacks preserve the delta intent: if nothing in the band is liquid, return
    the closest-delta band contract (G4 then rejects it -> No Trade, correctly);
    if the band is empty, fall back to the DTE window.
    """
    lo_dte, hi_dte = p.dte_range
    if decision == Decision.MOONSHOT:
        lo_d, hi_d = p.moon_delta_range
        target = p.moon_delta_target
    else:
        lo_d, hi_d = p.std_delta_range
        target = p.std_delta_target

    in_window = [c for c in s.contracts if lo_dte <= c.dte <= hi_dte]
    in_band = [c for c in in_window if lo_d <= c.delta <= hi_d]

    def closest(pool: list[OptionContract]) -> OptionContract | None:
        return min(pool, key=lambda c: abs(c.delta - target)) if pool else None

    tradeable = [c for c in in_band if gates.g4_contract_tradeable(c, p, enforce_volume)]
    if tradeable:
        return closest(tradeable)
    if in_band:
        return closest(in_band)
    return closest(in_window)


@dataclass
class ExitPlan:
    breakeven: float
    lines: list[str]


def build_exit_plan(
    contract: OptionContract,
    decision: Decision,
    atr: float,
    p: Params = PARAMS,
) -> ExitPlan:
    """Translate the section-7 rules into concrete dollar levels for the alert.
    Premium is execution-only -- used here for sizing/levels, never scored."""
    debit = contract.mid
    breakeven = contract.strike + debit

    if decision == Decision.MOONSHOT:
        scale_price = debit * (1 + p.moon_scale_out_pct)
        lines = [
            f"Sell HALF at +{p.moon_scale_out_pct*100:.0f}% (${scale_price:.2f})  -> bank the win",
            f"Runner: stop to break-even, trail {p.moon_runner_trail_atr:g}xATR "
            f"(~${atr:.2f} underlying), target "
            f"+{p.moon_runner_target_low*100:.0f}-{p.moon_runner_target_high*100:.0f}%",
        ]
    else:
        target_price = debit * (1 + p.std_target_pct)
        stop_price = debit * (1 + p.std_stop_pct)
        lines = [
            f"+{p.std_target_pct*100:.0f}% (${target_price:.2f}) -> close all",
            f"Stop -{abs(p.std_stop_pct)*100:.0f}% (${stop_price:.2f}), hard",
            f"Time-stop < {p.std_time_stop_dte} DTE with no progress",
        ]
    return ExitPlan(breakeven=round(breakeven, 2), lines=lines)
