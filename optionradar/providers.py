"""Data providers feeding the pipeline.

A provider answers three questions for the pipeline:
  * daily candles for a symbol
  * the call option chain for a symbol
  * days until the next earnings for a symbol

`SchwabProvider` is the production source (single data source, spec 11.1).
`MockProvider` generates deterministic synthetic data so the full pipeline can
be exercised offline / in tests without credentials.
"""

from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path
from typing import Protocol

from .data import parse_chain
from .models import OptionContract
from .schwab_client import SchwabClient


class DataProvider(Protocol):
    def candles(self, symbol: str) -> list[dict]: ...
    def chain(self, symbol: str) -> list[OptionContract]: ...
    def days_to_earnings(self, symbol: str) -> int | None: ...


# --------------------------------------------------------------------------- #
# Schwab (production)
# --------------------------------------------------------------------------- #
class SchwabProvider:
    def __init__(self, client: SchwabClient | None = None,
                 earnings_path: str | Path | None = None):
        self.client = client or SchwabClient()
        self.client.refresh_access_token()  # refresh at top of run (11.1)
        # Earnings dates come from a small committed calendar JSON
        # {symbol: "YYYY-MM-DD"}. Refresh it however you like; gaps -> "clear".
        self._earnings = {}
        path = Path(earnings_path) if earnings_path else (
            Path(__file__).resolve().parent.parent / "data" / "earnings.json")
        if path.exists():
            self._earnings = json.loads(path.read_text())

    def candles(self, symbol: str) -> list[dict]:
        return self.client.price_history(symbol)

    def chain(self, symbol: str) -> list[OptionContract]:
        raw = self.client.option_chain(symbol)
        return parse_chain(raw)

    def days_to_earnings(self, symbol: str) -> int | None:
        import datetime as _dt
        iso = self._earnings.get(symbol)
        if not iso:
            return None
        try:
            d = _dt.date.fromisoformat(iso)
        except ValueError:
            return None
        return (d - _dt.date.today()).days


# --------------------------------------------------------------------------- #
# Mock (offline / tests)
# --------------------------------------------------------------------------- #
class MockProvider:
    """Deterministic synthetic candles + chains. Seeded per symbol so a given
    symbol always produces the same series. Lets you run the whole pipeline and
    eyeball the Telegram cards without Schwab access."""

    def __init__(self, days: int = 320, seed: int = 7):
        self.days = days
        self.seed = seed

    def candles(self, symbol: str) -> list[dict]:
        rng = random.Random(f"{self.seed}:{symbol}")
        # Different symbols get different drift/vol so leadership varies.
        drift = rng.uniform(-0.0003, 0.0012)
        vol = rng.uniform(0.012, 0.03)
        price = rng.uniform(50, 400)
        out = []
        import datetime as _dt
        start = _dt.date.today() - _dt.timedelta(days=self.days * 2)
        d = start
        for _ in range(self.days):
            # skip weekends to look like trading days
            while d.weekday() >= 5:
                d += _dt.timedelta(days=1)
            ret = rng.gauss(drift, vol)
            new = max(1.0, price * (1 + ret))
            hi = max(price, new) * (1 + abs(rng.gauss(0, vol / 2)))
            lo = min(price, new) * (1 - abs(rng.gauss(0, vol / 2)))
            out.append({
                "date": d.isoformat(),
                "open": round(price, 2),
                "high": round(hi, 2),
                "low": round(lo, 2),
                "close": round(new, 2),
                "volume": int(rng.uniform(2_000_000, 40_000_000)),
            })
            price = new
            d += _dt.timedelta(days=1)
        return out

    def chain(self, symbol: str) -> list[OptionContract]:
        rng = random.Random(f"{self.seed}:chain:{symbol}")
        spot = self.candles(symbol)[-1]["close"]
        iv = rng.uniform(0.20, 0.55)
        contracts = []
        for dte in (45, 52, 58):
            for k in range(-6, 7):
                strike = round(spot * (1 + 0.025 * k), 0)
                # crude delta proxy from moneyness
                delta = max(0.05, min(0.95, 0.5 - 0.5 * (strike - spot) / (spot * 0.15)))
                mid = max(0.05, spot * iv * math.sqrt(dte / 365) * (0.4 + 0.6 * delta))
                spread = mid * rng.uniform(0.01, 0.04)
                contracts.append(OptionContract(
                    symbol=symbol, expiry="mock", dte=dte, strike=strike,
                    bid=round(mid - spread / 2, 2), ask=round(mid + spread / 2, 2),
                    mid=round(mid, 2), delta=round(delta, 2), iv=round(iv, 4),
                    open_interest=int(rng.uniform(300, 5000)),
                    volume=int(rng.uniform(20, 800)),
                ))
        return contracts

    def days_to_earnings(self, symbol: str) -> int | None:
        return random.Random(f"{self.seed}:earn:{symbol}").choice(
            [None, 70, 90, 120, 12, 200])
