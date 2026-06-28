#!/usr/bin/env python3
"""Explain a run: read the audit log and show why each name passed or failed.

Every daily run records each scanned name's gate results (and factor scores if
it survived) in the run_audit table. This script reads the latest run (or a
given --date) and prints a per-name gate grid plus a tally of which gate
eliminated the most names -- the fastest way to see whether a threshold is doing
its job (spec 11.4 #2).

Usage:
    python -m scripts.diagnose                 # latest run in the default store
    python -m scripts.diagnose --date 2026-06-20
    python -m scripts.diagnose --db data/iv_history.sqlite
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optionradar.iv_store import IVStore  # noqa: E402

GATE_IDS = ["G1", "G2", "G3", "G4", "G5"]
GATE_DESC = {
    "G1": "trend intact (close > EMA50 & EMA200)",
    "G2": "not a blow-off (RSI<75, <1.5 ATR over EMA20)",
    "G3": "moves enough (ATR/close >= 1.5%)",
    "G4": "contract tradeable (spread/OI/vol on the strike)",
    "G5": "earnings clear (> 50 days out)",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Explain an OptionRadar run")
    ap.add_argument("--date", default=None)
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    store = IVStore(args.db) if args.db else IVStore()
    conn = store.conn

    date = args.date
    if date is None:
        row = conn.execute("SELECT MAX(date) AS d FROM run_audit").fetchone()
        date = row["d"]
    if not date:
        print("No audit rows found. Run a scan first.")
        return 1

    rows = conn.execute(
        "SELECT symbol, payload FROM run_audit WHERE date=? ORDER BY symbol",
        (date,),
    ).fetchall()

    print(f"=== Run audit for {date} ({len(rows)} names) ===\n")
    if rows:
        first = json.loads(rows[0]["payload"])
        if first.get("volume_enforced") is False:
            print("NOTE: run was off-hours -> G4 day-volume floor NOT enforced "
                  "(spread + OI still checked). Volume numbers below are stale.\n")
    header = f"{'SYM':<6} " + " ".join(f"{g:>3}" for g in GATE_IDS) + "   passed  composite"
    print(header)
    print("-" * len(header))

    fail_counter: Counter[str] = Counter()
    passed_count = 0
    for r in rows:
        p = json.loads(r["payload"])
        gates = p.get("gates", {})
        marks = " ".join("  ." if gates.get(g) else "  X" for g in GATE_IDS)
        passed = p.get("passed", all(gates.get(g) for g in GATE_IDS) if gates else False)
        if passed:
            passed_count += 1
        else:
            for g in GATE_IDS:
                if not gates.get(g):
                    fail_counter[g] += 1
        comp = p.get("composite")
        comp_s = f"{comp:>6.1f}" if comp is not None else "     -"
        print(f"{r['symbol']:<6} {marks}   {'YES' if passed else ' no':>6}  {comp_s}")

    print("\nWhy names were dropped (count of names failing each gate):")
    for g in GATE_IDS:
        n = fail_counter.get(g, 0)
        bar = "#" * n
        print(f"  {g} {GATE_DESC[g]:<48} {n:>2} {bar}")
    print(f"\n{passed_count} of {len(rows)} names passed all gates.")

    # --- G4 detail: the actual numbers behind the liquidity gate ---
    # Thresholds: spread <= 5%, OI >= 500, day-vol >= 50 (PARAMS, spec section 10).
    print("\nG4 detail (selected ~0.62-delta strike; X marks the binding limit):")
    print(f"  {'SYM':<6} {'strike':>7} {'dte':>4} {'delta':>6} "
          f"{'spread%':>8} {'OI':>7} {'day-vol':>8}  chain")
    any_g4 = False
    for r in rows:
        p = json.loads(r["payload"])
        g4 = p.get("g4")
        n_chain = p.get("contracts_in_chain")
        if g4 is None:
            print(f"  {r['symbol']:<6} {'— no contract in DTE window —':<44} "
                  f"chain {n_chain}")
            any_g4 = True
            continue
        sp = g4["spread_pct"] * 100
        sp_f = "X" if g4["spread_pct"] > 0.05 else " "
        oi_f = "X" if g4["oi"] < 500 else " "
        vol_f = "X" if g4["vol"] < 50 else " "
        print(f"  {r['symbol']:<6} {g4['strike']:>7g} {g4['dte']:>4} "
              f"{g4['delta']:>6.2f} {sp:>7.1f}{sp_f} {g4['oi']:>6}{oi_f} "
              f"{g4['vol']:>7}{vol_f}  {n_chain}")
        any_g4 = True
    if not any_g4:
        print("  (no g4 data in this run -- re-run the scan to populate it)")

    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
