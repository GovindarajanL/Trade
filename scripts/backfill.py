#!/usr/bin/env python3
"""One-time IV-history backfill (spec 11.3).

IV Percentile (F2) needs ~252 days of history, fetched ONCE, backward -- not
collected forward. After this runs the system is at full strength on day one,
moonshots included. The daily run then only maintains the trailing window.

Fallback ladder (spec 11.3) if per-contract historical IV can't be pulled:
    --mode schwab   Schwab historical-chain backfill (best, default)
    --mode rvol     seed with realized vol from pricehistory as a stand-in
    --mode none     start empty; daily run grows it forward (warm-up labels)

Usage:
    python -m scripts.backfill --mode rvol          # offline-safe seed
    python -m scripts.backfill --mode schwab        # needs Schwab creds
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optionradar.env import load_dotenv  # noqa: E402

load_dotenv()  # pick up .env for local runs (no-op in GitHub Actions)

from optionradar.config import UNIVERSE, PARAMS  # noqa: E402
from optionradar.data import atm_iv_snapshot, parse_chain  # noqa: E402
from optionradar.indicators import realized_vol  # noqa: E402
from optionradar.iv_store import IVStore  # noqa: E402


def backfill_rvol(store: IVStore, days: int) -> int:
    """Cheap proxy seed: rolling realized vol from daily candles as an IV
    stand-in. Less precise; true IV snapshots overwrite it day by day."""
    from optionradar.providers import MockProvider, SchwabProvider
    try:
        provider = SchwabProvider()
    except Exception:
        print("[backfill] no Schwab creds -> using MockProvider for rvol seed")
        provider = MockProvider(days=days + 40)

    rows = []
    for n, name in enumerate(UNIVERSE, start=1):
        print(f"[backfill] rvol {n}/{len(UNIVERSE)} {name.symbol} ...", flush=True)
        candles = provider.candles(name.symbol)
        # walk forward, writing a realized-vol reading per day once we have
        # enough trailing window
        for i in range(40, len(candles)):
            rv = realized_vol(candles[: i + 1], window=20)
            if rv is not None:
                rows.append((candles[i]["date"], name.symbol, rv))
    written = store.backfill_rows(rows)
    print(f"[backfill] rvol seed wrote {written} rows")
    return written


def backfill_schwab(store: IVStore, days: int) -> int:
    """Best path: pull historical chains for ~last `days` trading days, extract
    ATM IV per day. Schwab dated-chain coverage is limited; gaps are skipped and
    you should fall back to --mode rvol for the remainder."""
    from optionradar.schwab_client import SchwabClient
    client = SchwabClient()
    client.refresh_access_token()

    rows = []
    today = _dt.date.today()
    for n, name in enumerate(UNIVERSE, start=1):
        print(f"[backfill] schwab {n}/{len(UNIVERSE)} {name.symbol} "
              f"(up to {days} historical chains) ...", flush=True)
        # daily candles give us the spot per historical date for ATM selection
        candles = {c["date"]: c for c in client.price_history(name.symbol)}
        for back in range(days):
            d = today - _dt.timedelta(days=back)
            iso = d.isoformat()
            if d.weekday() >= 5 or iso not in candles:
                continue
            try:
                raw = client.historical_option_chain(name.symbol, iso)
                contracts = parse_chain(raw)
                iv = atm_iv_snapshot(contracts, candles[iso]["close"])
                if iv is not None:
                    rows.append((iso, name.symbol, iv))
            except Exception as exc:  # noqa: BLE001
                print(f"[backfill] {name.symbol} {iso} skipped: {exc}")
    written = store.backfill_rows(rows)
    print(f"[backfill] schwab wrote {written} rows")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="One-time IV-history backfill")
    ap.add_argument("--mode", choices=["schwab", "rvol", "none"], default="schwab")
    ap.add_argument("--days", type=int, default=PARAMS.iv_percentile_window)
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    store = IVStore(args.db) if args.db else IVStore()
    try:
        if args.mode == "schwab":
            backfill_schwab(store, args.days)
        elif args.mode == "rvol":
            backfill_rvol(store, args.days)
        else:
            print("[backfill] mode=none: starting empty; daily run warms up forward")
        depths = {n.symbol: store.history_depth(n.symbol) for n in UNIVERSE}
        shallow = min(depths.values()) if depths else 0
        print(f"[backfill] shallowest history depth: {shallow} days")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
