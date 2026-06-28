"""Stage 1 -- Gates (spec section 3).

Binary. ALL must pass or the name is dropped. No scoring here; survivors are
already trade-worthy before ranking. A name between its 50 and 200 EMA fails G1
-- that is intended; the chop zone between the averages is where directional
options die.

G4 (contract tradeable) needs an option contract. The pipeline runs G1-G3 and
G5 on the underlying first, then checks G4 against the best candidate strike.
`best_call` is the contract chosen for the trade (see strike.py); if no chain
is available G4 fails.
"""

from __future__ import annotations

from .config import PARAMS, Params
from .models import GateResult, NameSnapshot, OptionContract


def g1_trend_intact(s: NameSnapshot) -> bool:
    return s.close > s.ema50 and s.close > s.ema200


def g2_not_blowoff(s: NameSnapshot, p: Params = PARAMS) -> bool:
    if s.rsi >= p.g2_rsi_cap:
        return False
    if s.atr <= 0:
        return False
    return (s.close - s.ema20) / s.atr < p.g2_atr_extension


def g3_moves_enough(s: NameSnapshot, p: Params = PARAMS) -> bool:
    if s.close <= 0:
        return False
    return (s.atr / s.close) >= p.g3_movement_floor


def g4_contract_tradeable(
    contract: OptionContract | None,
    p: Params = PARAMS,
    enforce_volume: bool = True,
) -> bool:
    if contract is None:
        return False
    if contract.spread_pct > p.g4_spread_max:
        return False
    if contract.open_interest < p.g4_oi_floor:
        return False
    # Day-volume is only enforced when it is a meaningful signal (market open /
    # post-close on a trading day). Off-hours it would be a zero artifact.
    if enforce_volume and contract.volume < p.g4_vol_floor:
        return False
    return True


def g5_earnings_clear(s: NameSnapshot, p: Params = PARAMS) -> bool:
    # No earnings date known -> treat as clear (calendar feed gap shouldn't
    # silently drop names; the buffer is the guard against a *known* event).
    if s.days_to_earnings is None:
        return True
    return s.days_to_earnings > p.g5_earnings_buffer_days


def evaluate(
    s: NameSnapshot,
    best_call: OptionContract | None,
    p: Params = PARAMS,
    enforce_volume: bool = True,
) -> GateResult:
    gates = {
        "G1": g1_trend_intact(s),
        "G2": g2_not_blowoff(s, p),
        "G3": g3_moves_enough(s, p),
        "G4": g4_contract_tradeable(best_call, p, enforce_volume),
        "G5": g5_earnings_clear(s, p),
    }
    failed = [k for k, v in gates.items() if not v]
    return GateResult(passed=not failed, gates=gates, failed=failed)
