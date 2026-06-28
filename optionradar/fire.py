"""Stage 3 -- Fire logic (spec section 5).

Rank survivors by composite, then test the #1 candidate. The score gets the
shortlist; the floor across factors and the gap to #2 certify the trade.

Outputs one of: NO_TRADE, STANDARD, MOONSHOT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .config import PARAMS, Params
from .models import Candidate, MarketRegime, ScoreResult


class Decision(str, Enum):
    NO_TRADE = "NO_TRADE"
    STANDARD = "STANDARD"
    MOONSHOT = "MOONSHOT"


@dataclass
class FireResult:
    decision: Decision
    top: Candidate | None
    runner_up: Candidate | None
    separation: float | None
    # human-readable reason a standard signal was blocked (for the No-Trade card)
    block_reason: str | None = None
    checks: dict = field(default_factory=dict)


def _min_factor(score: ScoreResult, fids) -> float:
    return min(score.factors[f] for f in fids)


def rank(candidates: list[Candidate]) -> list[Candidate]:
    ordered = sorted(candidates, key=lambda c: c.score.composite, reverse=True)
    for i, c in enumerate(ordered, start=1):
        c.score.rank = i
    return ordered


def evaluate(
    candidates: list[Candidate],
    regime: MarketRegime,
    p: Params = PARAMS,
    moonshots_allowed: bool = True,
) -> FireResult:
    """`moonshots_allowed` is False while the IV store is still warming up
    (< 252 days of history); see spec 11.3."""
    if not candidates:
        return FireResult(Decision.NO_TRADE, None, None, None,
                          block_reason="no survivors passed the gates")

    ordered = rank(candidates)
    top = ordered[0]
    runner = ordered[1] if len(ordered) > 1 else None
    separation = (top.score.composite - runner.score.composite) if runner else top.score.composite

    # --- market-regime bumps (section 5 note) ---
    composite_min = p.std_composite_min
    separation_min = p.std_separation_min
    if not regime.spy_above_50_200:
        composite_min = p.weak_tape_composite_min
        separation_min = p.weak_tape_separation_min

    f = top.score.factors
    checks = {
        "composite": (top.score.composite, composite_min,
                      top.score.composite >= composite_min),
        "no_weak_link": (_min_factor(top.score, p.std_core_factors),
                         p.std_core_factor_min,
                         _min_factor(top.score, p.std_core_factors) >= p.std_core_factor_min),
        "confluence": (sum(1 for v in f.values() if v >= p.std_confluence_threshold),
                       p.std_confluence_count,
                       sum(1 for v in f.values() if v >= p.std_confluence_threshold) >= p.std_confluence_count),
        "separation": (round(separation, 1), separation_min, separation >= separation_min),
    }

    fires = all(c[2] for c in checks.values())
    if not fires:
        return FireResult(
            Decision.NO_TRADE, top, runner, round(separation, 1),
            block_reason=_block_reason(checks, runner),
            checks=checks,
        )

    # --- Moonshot upgrade ---
    moon_checks = {
        "composite": (top.score.composite, p.moon_composite_min,
                      top.score.composite >= p.moon_composite_min),
        "all_factors": (_min_factor(top.score, f.keys()), p.moon_all_factor_min,
                        _min_factor(top.score, f.keys()) >= p.moon_all_factor_min),
        "contradiction": (f["F2"], f["F5"], f["F2"] >= p.moon_f2_min and f["F5"] >= p.moon_f5_min),
        "runway": (f["F4"], p.moon_f4_min, f["F4"] >= p.moon_f4_min),
        "separation": (round(separation, 1), p.moon_separation_min, separation >= p.moon_separation_min),
    }
    if moonshots_allowed and all(c[2] for c in moon_checks.values()):
        return FireResult(Decision.MOONSHOT, top, runner, round(separation, 1),
                          checks={**checks, "moonshot": moon_checks})

    return FireResult(Decision.STANDARD, top, runner, round(separation, 1), checks=checks)


def _block_reason(checks: dict, runner: Candidate | None) -> str:
    """Pick the most informative failing check for the No-Trade card."""
    if not checks["composite"][2]:
        val, need, _ = checks["composite"]
        return f"composite {val:.0f} < {need:.0f}"
    if not checks["no_weak_link"][2]:
        val, need, _ = checks["no_weak_link"]
        return f"weak core factor {val:.0f} < {need:.0f}"
    if not checks["confluence"][2]:
        val, need, _ = checks["confluence"]
        return f"confluence {val} of 7 < {need}"
    if not checks["separation"][2]:
        val, need, _ = checks["separation"]
        ru = f" (#2 {runner.snapshot.symbol} {runner.score.composite:.0f})" if runner else ""
        return f"separation {val:.0f} < {need:.0f}{ru}"
    return "blocked"
