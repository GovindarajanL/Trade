"""US market clock + run-window logic.

GitHub Actions cron is UTC-only and ignores US daylight-saving time, and
scheduled jobs can be *delayed* (never early) under load. To run reliably at a
fixed Eastern-time moment we schedule two UTC crons (one per DST offset) and let
this module decide which firing should actually do work.

The two crons for a given job are 60 minutes apart in UTC. In any given season
exactly one of them lands inside the target window below; the other is rejected.
A modest GitHub delay still lands inside the window. Belt-and-suspenders dedup
(don't run the evening scan twice for the same date) lives in the pipeline via
the committed IV store.

Eastern time is resolved with zoneinfo when available, falling back to a manual
US DST calculation so there is no hard dependency (handy on Windows, where the
OS ships no tz database).
"""

from __future__ import annotations

import datetime as _dt

try:  # preferred: real tz database
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback path
    _ET = None


# NYSE full-day holidays (markets closed). Update yearly. Half-days are ignored
# (the scan still produces useful signals on a half day).
MARKET_HOLIDAYS = {
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """nth (1-based) `weekday` (Mon=0) of month."""
    d = _dt.date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + _dt.timedelta(days=offset + 7 * (n - 1))


def _is_us_dst(utc: _dt.datetime) -> bool:
    """US Eastern observes DST from 2nd Sunday of March 07:00 UTC to 1st Sunday
    of November 06:00 UTC (02:00 local transitions)."""
    y = utc.year
    start = _dt.datetime.combine(_nth_weekday(y, 3, 6, 2), _dt.time(7))
    end = _dt.datetime.combine(_nth_weekday(y, 11, 6, 1), _dt.time(6))
    naive = utc.replace(tzinfo=None)
    return start <= naive < end


def now_et(utc_now: _dt.datetime | None = None) -> _dt.datetime:
    """Current Eastern time (tz-aware if zoneinfo is available)."""
    utc_now = utc_now or _dt.datetime.now(_dt.timezone.utc)
    if _ET is not None:
        return utc_now.astimezone(_ET)
    offset = -4 if _is_us_dst(utc_now) else -5
    return (utc_now + _dt.timedelta(hours=offset)).replace(tzinfo=None)


def et_date(et: _dt.datetime | None = None) -> str:
    return (et or now_et()).date().isoformat()


def _is_trading_day(et: _dt.datetime) -> bool:
    return et.weekday() < 5 and et.date().isoformat() not in MARKET_HOLIDAYS


# Target run windows in Eastern time. Width < 60 min so the off-season cron
# firing (always ~60 min from target) is excluded, but wide enough to absorb a
# typical GitHub scheduling delay (which only pushes later).
EVENING_WINDOW = (_dt.time(16, 5), _dt.time(17, 15))   # just after the 4:00 close
MORNING_WINDOW = (_dt.time(9, 35), _dt.time(10, 15))    # just after the 9:30 open


def _in_window(et: _dt.datetime, window: tuple[_dt.time, _dt.time]) -> bool:
    start, end = window
    return start <= et.time() <= end


MARKET_OPEN = _dt.time(9, 30)


def volume_meaningful(et: _dt.datetime | None = None) -> bool:
    """Is option day-volume a real signal right now?

    True only on a trading day at/after the 9:30 ET open (intraday or after the
    close, when the session's volume tally stands). False pre-open, on weekends,
    and on holidays -- there the chain shows zero/stale volume, so the G4
    day-volume floor would spuriously reject everything. Spread and open-interest
    are always meaningful and stay enforced.
    """
    et = et or now_et()
    return _is_trading_day(et) and et.time() >= MARKET_OPEN


def should_run(kind: str, et: _dt.datetime | None = None) -> tuple[bool, str]:
    """Return (ok, reason). `kind` is 'evening' or 'morning'."""
    et = et or now_et()
    if not _is_trading_day(et):
        return False, f"{et.date()} is a weekend or market holiday"
    window = EVENING_WINDOW if kind == "evening" else MORNING_WINDOW
    if not _in_window(et, window):
        return False, (f"{et.strftime('%H:%M')} ET is outside the {kind} window "
                       f"{window[0].strftime('%H:%M')}-{window[1].strftime('%H:%M')} ET")
    return True, f"{et.strftime('%H:%M')} ET, {kind} window"
