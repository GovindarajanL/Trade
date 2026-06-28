#!/usr/bin/env python3
"""Inspect a live option chain for one symbol and explain G4.

Fetches the chain for a single symbol, shows how many contracts came back, the
strike the pipeline would pick, and the exact spread / open-interest / day-volume
on it -- so you can see precisely which part of G4 (contract tradeable) passes or
fails. Day-volume is 0 when the market is closed (weekend / holiday), which fails
the volume floor for every name; that is expected, not a bug.

Usage:
    python -m scripts.inspect_chain NVDA
    python -m scripts.inspect_chain SPY --moon
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optionradar.env import load_dotenv  # noqa: E402

load_dotenv()

from optionradar.config import PARAMS  # noqa: E402
from optionradar.fire import Decision  # noqa: E402
from optionradar.providers import SchwabProvider  # noqa: E402
from optionradar.strike import select_contract  # noqa: E402
from optionradar.models import NameSnapshot  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect one option chain")
    ap.add_argument("symbol")
    ap.add_argument("--moon", action="store_true", help="use Moonshot delta band")
    args = ap.parse_args()
    sym = args.symbol.upper()
    p = PARAMS

    provider = SchwabProvider()
    candles = provider.candles(sym)
    if not candles:
        print(f"No candles for {sym}")
        return 1
    spot = float(candles[-1]["close"])
    contracts = provider.chain(sym)
    print(f"{sym}: spot ~{spot:.2f} · {len(contracts)} call contracts returned")

    if not contracts:
        print("Chain came back EMPTY -> G4 cannot pass. "
              "Check the chains endpoint / parse_chain field names.")
        return 1

    # show the DTE spread and a few sample strikes near the money
    dtes = sorted({c.dte for c in contracts})
    print(f"DTEs available: {dtes}")
    near = sorted(contracts, key=lambda c: abs(c.strike - spot))[:5]
    print("\nNearest-the-money samples:")
    print(f"  {'strike':>8} {'dte':>4} {'delta':>6} {'bid':>7} {'ask':>7} "
          f"{'mid':>7} {'spread%':>8} {'OI':>7} {'vol':>6}")
    for c in near:
        print(f"  {c.strike:>8g} {c.dte:>4} {c.delta:>6.2f} {c.bid:>7.2f} "
              f"{c.ask:>7.2f} {c.mid:>7.2f} {c.spread_pct*100:>7.1f}% "
              f"{c.open_interest:>7} {c.volume:>6}")

    # what the pipeline would actually pick
    snap = NameSnapshot(
        symbol=sym, bucket="", sector_etf="", close=spot, volume=0,
        ema20=spot, ema50=spot, ema200=spot, ema50_slope_up=True, rsi=50,
        atr=spot * 0.02, avg_vol_20=1, up_day=True, full_stack=True,
        dist_to_ema20_atr=0, range_contraction=0, atr_to_resistance=5,
        rel_strength={}, iv_percentile=None, days_to_earnings=None,
        contracts=contracts,
    )
    decision = Decision.MOONSHOT if args.moon else Decision.STANDARD
    chosen = select_contract(snap, decision, p)
    print(f"\nPipeline would pick (target delta "
          f"{p.moon_delta_target if args.moon else p.std_delta_target}):")
    if chosen is None:
        print("  none in the DTE window")
        return 0
    print(f"  strike {chosen.strike:g}, dte {chosen.dte}, delta {chosen.delta:.2f}")
    checks = {
        f"spread {chosen.spread_pct*100:.1f}% <= {p.g4_spread_max*100:.0f}%":
            chosen.spread_pct <= p.g4_spread_max,
        f"OI {chosen.open_interest} >= {p.g4_oi_floor}":
            chosen.open_interest >= p.g4_oi_floor,
        f"day-volume {chosen.volume} >= {p.g4_vol_floor}":
            chosen.volume >= p.g4_vol_floor,
    }
    print("\nG4 on this strike:")
    for desc, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
    if all(checks.values()):
        print("\n-> G4 PASSES.")
    else:
        print("\n-> G4 FAILS. If only day-volume fails and it is the weekend, "
              "this is expected; re-run on a trading day.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
