#!/usr/bin/env python3
"""Daily OptionRadar run (spec section 9).

Usage:
    python -m scripts.run_daily                 # live: Schwab provider
    python -m scripts.run_daily --mock          # offline synthetic data
    python -m scripts.run_daily --no-send       # build the card but don't send
    python -m scripts.run_daily --db data/iv_history.sqlite

Always sends something (firing card or No-Trade card). Read-only; emits to
Telegram only -- entry is manual.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optionradar.env import load_dotenv  # noqa: E402

load_dotenv()  # pick up .env for local runs (no-op in GitHub Actions)

from optionradar import telegram  # noqa: E402
from optionradar.iv_store import IVStore  # noqa: E402
from optionradar import market  # noqa: E402
from optionradar.pipeline import run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="OptionRadar daily scan")
    ap.add_argument("--mock", action="store_true", help="use synthetic data (no Schwab)")
    ap.add_argument("--no-send", action="store_true", help="don't send to Telegram")
    ap.add_argument("--db", default=None, help="path to IV-history SQLite store")
    ap.add_argument("--date", default=None, help="override run date (YYYY-MM-DD)")
    ap.add_argument("--force", action="store_true", help="skip the time-window guard")
    args = ap.parse_args()

    if not args.force:
        ok, why = market.should_run("evening")
        if not ok:
            print(f"[evening] skipping: {why}")
            return 0

    if args.mock:
        from optionradar.providers import MockProvider
        provider = MockProvider()
    else:
        from optionradar.providers import SchwabProvider
        provider = SchwabProvider()

    store = IVStore(args.db) if args.db else IVStore()
    # Dedup: if the off-season cron firing was delayed into the window and the
    # scan already ran for today, don't run it twice (the committed signal is
    # the marker).
    run_date = args.date or market.et_date()
    if not args.force and store.signal_for(run_date) is not None:
        print(f"[evening] already ran for {run_date}; skipping.")
        store.close()
        return 0
    try:
        result = run(provider, store, today=args.date)
    finally:
        store.close()

    print(f"\n=== OptionRadar {result.date} ===")
    print(f"scanned {result.scanned} · past gates {result.past_gates} · "
          f"decision {result.fire_result.decision.value}")
    print("-" * 60)
    print(result.alert.text)
    print("-" * 60)

    if not args.no_send:
        telegram.send(result.alert.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
