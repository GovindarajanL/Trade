"""The IV-history store -- "the database is just the repo" (spec 11.2).

A single SQLite file committed to the repo holds one row per (date, symbol):
the ATM implied volatility snapshotted that day. The whole thing is kilobytes
(24 symbols x ~252 days x a few floats).

  * append_snapshot()  -- daily maintenance: write today's ATM IV per symbol.
  * iv_percentile()    -- F2 input: % of the last N stored IVs below today's.
  * audit log          -- each run also stores the day's survivors + scores so
                          the No-Trade card can explain itself and you can audit
                          whether the thresholds did their job (spec 11.4 #2).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "iv_history.sqlite"


class IVStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS iv_history (
                date   TEXT NOT NULL,
                symbol TEXT NOT NULL,
                atm_iv REAL NOT NULL,
                PRIMARY KEY (date, symbol)
            );
            CREATE TABLE IF NOT EXISTS run_audit (
                date    TEXT NOT NULL,
                symbol  TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (date, symbol)
            );
            CREATE TABLE IF NOT EXISTS signals (
                date    TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    # ----- daily maintenance ------------------------------------------- #
    def append_snapshot(self, date: str, symbol: str, atm_iv: float) -> None:
        """Idempotent upsert of one ATM IV reading."""
        self.conn.execute(
            "INSERT INTO iv_history(date, symbol, atm_iv) VALUES (?,?,?) "
            "ON CONFLICT(date, symbol) DO UPDATE SET atm_iv=excluded.atm_iv",
            (date, symbol, float(atm_iv)),
        )
        self.conn.commit()

    def backfill_rows(self, rows: list[tuple[str, str, float]]) -> int:
        """Bulk insert (date, symbol, atm_iv) rows for the one-time backfill."""
        self.conn.executemany(
            "INSERT INTO iv_history(date, symbol, atm_iv) VALUES (?,?,?) "
            "ON CONFLICT(date, symbol) DO UPDATE SET atm_iv=excluded.atm_iv",
            [(d, s, float(v)) for d, s, v in rows],
        )
        self.conn.commit()
        return len(rows)

    # ----- F2 input ----------------------------------------------------- #
    def _history(self, symbol: str, window: int, before_date: str | None) -> list[float]:
        if before_date:
            cur = self.conn.execute(
                "SELECT atm_iv FROM iv_history WHERE symbol=? AND date < ? "
                "ORDER BY date DESC LIMIT ?",
                (symbol, before_date, window),
            )
        else:
            cur = self.conn.execute(
                "SELECT atm_iv FROM iv_history WHERE symbol=? "
                "ORDER BY date DESC LIMIT ?",
                (symbol, window),
            )
        return [r["atm_iv"] for r in cur.fetchall()]

    def history_depth(self, symbol: str) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) AS c FROM iv_history WHERE symbol=?", (symbol,)
        )
        return cur.fetchone()["c"]

    def iv_percentile(
        self,
        symbol: str,
        today_iv: float,
        window: int = 252,
        before_date: str | None = None,
    ) -> float | None:
        """Percentile of `today_iv` against the last `window` stored readings:
        the percentage of historical IVs strictly below today's value.

        Returns None if there is no stored history to compare against.
        Percentile (not rank) is used deliberately -- robust to one-day spikes,
        and it is literally what "lowest in N months" means (spec 11.2).
        """
        hist = self._history(symbol, window, before_date)
        if not hist:
            return None
        below = sum(1 for v in hist if v < today_iv)
        return 100.0 * below / len(hist)

    def months_of_history(self, symbol: str) -> int:
        """Approximate calendar months represented (~21 trading days/month).
        Used for the "lowest in N months" alert line."""
        depth = self.history_depth(symbol)
        return max(1, round(depth / 21))

    # ----- audit -------------------------------------------------------- #
    def record_audit(self, date: str, symbol: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO run_audit(date, symbol, payload) VALUES (?,?,?) "
            "ON CONFLICT(date, symbol) DO UPDATE SET payload=excluded.payload",
            (date, symbol, json.dumps(payload, default=str)),
        )
        self.conn.commit()

    # ----- signals (what the evening scan decided; read by the morning check) -- #
    def record_signal(self, date: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO signals(date, payload) VALUES (?,?) "
            "ON CONFLICT(date) DO UPDATE SET payload=excluded.payload",
            (date, json.dumps(payload, default=str)),
        )
        self.conn.commit()

    def signal_for(self, date: str) -> dict | None:
        row = self.conn.execute(
            "SELECT payload FROM signals WHERE date=?", (date,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def latest_signal(self) -> dict | None:
        row = self.conn.execute(
            "SELECT payload FROM signals ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "IVStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
