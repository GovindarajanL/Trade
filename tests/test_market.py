import datetime as dt

from optionradar import market


def _et(y, m, d, hh, mm):
    utc = dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc)
    return market.now_et(utc)


# --- Summer (EDT, UTC-4): July 1 2026 is a Wednesday ---
def test_evening_summer_correct_cron_runs():
    assert market.should_run("evening", _et(2026, 7, 1, 20, 30))[0]   # 16:30 ET


def test_evening_summer_wrong_cron_skips():
    assert not market.should_run("evening", _et(2026, 7, 1, 21, 30))[0]  # 17:30 ET


def test_morning_summer_correct_cron_runs():
    assert market.should_run("morning", _et(2026, 7, 1, 13, 45))[0]   # 09:45 ET


def test_morning_summer_wrong_cron_skips():
    assert not market.should_run("morning", _et(2026, 7, 1, 14, 45))[0]  # 10:45 ET


# --- Winter (EST, UTC-5): Jan 6 2026 is a Tuesday ---
def test_evening_winter_correct_cron_runs():
    assert market.should_run("evening", _et(2026, 1, 6, 21, 30))[0]   # 16:30 ET


def test_evening_winter_wrong_cron_skips():
    assert not market.should_run("evening", _et(2026, 1, 6, 20, 30))[0]  # 15:30 ET


def test_morning_winter_correct_cron_runs():
    assert market.should_run("morning", _et(2026, 1, 6, 14, 45))[0]   # 09:45 ET


def test_morning_winter_wrong_cron_skips():
    assert not market.should_run("morning", _et(2026, 1, 6, 13, 45))[0]  # 08:45 ET


# --- weekends and holidays ---
def test_weekend_never_runs():
    # 2026-06-20 is a Saturday
    assert not market.should_run("evening", _et(2026, 6, 20, 20, 30))[0]


def test_holiday_never_runs():
    # 2026-12-25 Christmas (a Friday)
    assert not market.should_run("evening", _et(2026, 12, 25, 21, 30))[0]


# --- day-volume meaningfulness (off-hours relaxation) ---
def test_volume_meaningful_during_session():
    # weekday 11:00 ET (summer) -> 15:00 UTC
    assert market.volume_meaningful(_et(2026, 7, 1, 15, 0))


def test_volume_meaningful_after_close_same_day():
    # 4:30 PM ET (evening scan time, summer) -> 20:30 UTC; tally still stands
    assert market.volume_meaningful(_et(2026, 7, 1, 20, 30))


def test_volume_not_meaningful_pre_open():
    # 8:00 AM ET (summer) -> 12:00 UTC, before the 9:30 open
    assert not market.volume_meaningful(_et(2026, 7, 1, 12, 0))


def test_volume_not_meaningful_on_weekend():
    # Saturday
    assert not market.volume_meaningful(_et(2026, 6, 20, 15, 0))
