"""Schwab market-data integration -- the single data source (spec 11.1).

Reuses the existing Schwab OAuth setup (the same one the TQQQ system uses).
Three endpoints cover everything:

  * GET /marketdata/v1/pricehistory       daily candles for every symbol
  * GET /marketdata/v1/chains             option chain per symbol; each contract
                                          already carries delta, volatility (IV),
                                          bid/ask, OI and volume -- no greeks are
                                          computed by hand
  * /marketdata/v1/chains with past dates historical chains for the one-time IV
                                          backfill (11.3), where available

Token handling is the only fragile part: refresh the access token at the top of
each run. Refresh tokens expire ~7 days; if a run fails on a stale token, re-auth
is manual. Client id/secret + refresh token live as GitHub Action secrets, never
in the repo.

This client is read-only. It never places, modifies, or cancels orders.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

API_BASE = "https://api.schwabapi.com"
TOKEN_URL = f"{API_BASE}/v1/oauth/token"
MARKETDATA = f"{API_BASE}/marketdata/v1"


@dataclass
class SchwabCredentials:
    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_env(cls) -> "SchwabCredentials":
        try:
            return cls(
                client_id=os.environ["SCHWAB_CLIENT_ID"],
                client_secret=os.environ["SCHWAB_CLIENT_SECRET"],
                refresh_token=os.environ["SCHWAB_REFRESH_TOKEN"],
            )
        except KeyError as exc:
            raise RuntimeError(
                f"Missing Schwab credential {exc}. Set SCHWAB_CLIENT_ID, "
                "SCHWAB_CLIENT_SECRET, SCHWAB_REFRESH_TOKEN (GitHub Action secrets)."
            ) from exc


class SchwabClient:
    def __init__(self, creds: SchwabCredentials | None = None):
        self.creds = creds or SchwabCredentials.from_env()
        self._access_token: str | None = None

    # ----- auth -------------------------------------------------------- #
    def refresh_access_token(self) -> str:
        """Exchange the refresh token for a fresh access token. Call once at the
        top of each run."""
        import base64

        basic = base64.b64encode(
            f"{self.creds.client_id}:{self.creds.client_secret}".encode()
        ).decode()
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self.creds.refresh_token,
        }).encode()
        req = urllib.request.Request(
            TOKEN_URL, data=data,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        self._access_token = payload["access_token"]
        return self._access_token

    def _get(self, url: str, params: dict) -> dict:
        if self._access_token is None:
            self.refresh_access_token()
        full = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            full, headers={"Authorization": f"Bearer {self._access_token}"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    # ----- endpoints --------------------------------------------------- #
    def price_history(
        self,
        symbol: str,
        days: int = 300,
    ) -> list[dict]:
        """Daily OHLCV candles. Returns a list of dicts ordered oldest->newest
        with keys date, open, high, low, close, volume."""
        params = {
            "symbol": symbol,
            "periodType": "year",
            "period": 2,
            "frequencyType": "daily",
            "frequency": 1,
            "needExtendedHoursData": "false",
        }
        raw = self._get(f"{MARKETDATA}/pricehistory", params)
        candles = []
        for c in raw.get("candles", []):
            candles.append({
                "date": time.strftime("%Y-%m-%d", time.gmtime(c["datetime"] / 1000)),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
            })
        return candles[-days:] if days else candles

    def option_chain(
        self,
        symbol: str,
        from_dte: int = 30,
        to_dte: int = 60,
        contract_type: str = "CALL",
    ) -> dict:
        """Raw Schwab option-chain payload for calls within a DTE window."""
        import datetime as _dt

        today = _dt.date.today()
        params = {
            "symbol": symbol,
            "contractType": contract_type,
            "strategy": "SINGLE",
            "fromDate": (today + _dt.timedelta(days=from_dte)).isoformat(),
            "toDate": (today + _dt.timedelta(days=to_dte)).isoformat(),
            "includeUnderlyingQuote": "true",
        }
        return self._get(f"{MARKETDATA}/chains", params)

    def historical_option_chain(self, symbol: str, on_date: str) -> dict:
        """Best-effort historical chain for the one-time IV backfill (11.3).
        Schwab support for dated chains is limited; callers must handle gaps and
        fall back per the 11.3 ladder."""
        params = {
            "symbol": symbol,
            "contractType": "CALL",
            "strategy": "SINGLE",
            "date": on_date,
        }
        return self._get(f"{MARKETDATA}/chains", params)
