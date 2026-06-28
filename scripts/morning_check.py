#!/usr/bin/env python3
"""Next-morning entry re-validation (~9:45 ET).

The evening scan emits a signal for next-session entry. This run, just after the
open when options are trading, re-validates that signal against the LIVE chain so
you know whether the trade you're about to place is still good:

  * re-pulls candles + chain for the fired symbol
  * re-runs the gates (did it gap below EMA50? into a blow-off? is the strike
    actually liquid right now?)
  * measures the overnight gap vs the signal's reference close
  * re-picks the strike at the target delta and prints a fresh cost range + exits

If the evening scan said No Trade, there is nothing to do and this exits quietly.

Usage:
    python -m scripts.morning_check               # live, sends to Telegram
    python -m scripts.morning_check --no-send
    python -m scripts.morning_check --force       # ignore the time-window guard
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optionradar.env import load_dotenv  # noqa: E402

load_dotenv()

from optionradar import data, gates, market, telegram  # noqa: E402
from optionradar.config import PARAMS, name_for  # noqa: E402
from optionradar.fire import Decision  # noqa: E402
from optionradar.iv_store import IVStore  # noqa: E402
from optionradar.strike import build_exit_plan, select_contract  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Morning entry re-validation")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--force", action="store_true", help="skip the time-window guard")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    if not args.force:
        ok, why = market.should_run("morning")
        if not ok:
            print(f"[morning] skipping: {why}")
            return 0

    store = IVStore(args.db) if args.db else IVStore()
    try:
        return _run(store, args)
    finally:
        store.close()


def _run(store: IVStore, args) -> int:
    signal = store.latest_signal()
    if not signal:
        print("[morning] no signal on record — run the evening scan first.")
        return 0
    if signal.get("decision") == Decision.NO_TRADE.value or not signal.get("symbol"):
        print(f"[morning] last signal ({signal.get('date')}) was No Trade — nothing to act on.")
        return 0

    sym = signal["symbol"]
    decision = Decision(signal["decision"])
    name = name_for(sym)
    if name is None:
        print(f"[morning] {sym} is no longer in the universe; skipping.")
        return 0

    if args.mock:
        from optionradar.providers import MockProvider
        provider = MockProvider()
    else:
        from optionradar.providers import SchwabProvider
        provider = SchwabProvider()

    candles = provider.candles(sym)
    sector_candles = provider.candles(name.sector_etf)
    spy_candles = provider.candles("SPY")
    contracts = provider.chain(sym)

    snap = data.build_snapshot(
        name=name, candles=candles, sector_candles=sector_candles,
        spy_candles=spy_candles, chain_contracts=contracts,
        iv_percentile=None, atm_iv=None,
        days_to_earnings=provider.days_to_earnings(sym), p=PARAMS,
    )
    if snap is None:
        print(f"[morning] not enough data to re-validate {sym}; check manually.")
        return 0

    # re-pick the strike on the live chain for the signalled tier, then re-gate
    enforce_volume = market.volume_meaningful()
    contract = select_contract(snap, decision, PARAMS, enforce_volume)
    gate = gates.evaluate(snap, contract, PARAMS, enforce_volume)

    # overnight gap vs the signal's reference close
    ref = signal.get("ref_close")
    gap_pct = gap_atr = None
    gap_warn = False
    if ref:
        gap_pct = (snap.close - ref) / ref
        if snap.atr > 0:
            gap_atr = (snap.close - ref) / snap.atr
            gap_warn = abs(gap_atr) >= PARAMS.morning_gap_atr_warn

    exits = build_exit_plan(contract, decision, snap.atr, PARAMS) if contract else None
    text = telegram.entry_check_card(
        signal=signal, contract=contract, exits=exits,
        gate_failed=gate.failed if not gate.passed else None,
        gap_pct=gap_pct, gap_atr=gap_atr, gap_warn=gap_warn,
    )

    print("-" * 60)
    print(text)
    print("-" * 60)
    if not args.no_send:
        telegram.send(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
