from datetime import UTC, datetime

from bot.utils.datetime_utils import fmt_ru_date_time, iso_utc, local_to_utc, parse_iso_utc, to_local


def test_iso_roundtrip():
    dt = datetime(2026, 1, 30, 12, 15, tzinfo=UTC)
    assert parse_iso_utc(iso_utc(dt)) == dt


def test_local_utc_conversion():
    utc_dt = datetime(2026, 1, 30, 12, 0, tzinfo=UTC)
    local_dt = to_local(utc_dt, 180)
    assert local_dt.hour == 15
    assert local_to_utc(local_dt.replace(tzinfo=None), 180) == utc_dt


def test_format_ru_date_time():
    utc_dt = datetime(2026, 2, 1, 11, 30, tzinfo=UTC)
    assert fmt_ru_date_time(utc_dt, 180) == "1 февраля в 14:30"
