from datetime import datetime

from bot.services.reminder_parser import next_repeat_time, parse_duration_to_timedelta, parse_reminder, parse_when_only


def test_parse_relative_minutes():
    now = datetime(2026, 1, 30, 10, 0)
    parsed = parse_reminder("10м созвон", now)
    assert parsed is not None
    assert parsed.text == "созвон"
    assert parsed.when_local == datetime(2026, 1, 30, 10, 10)


def test_parse_absolute_ru_date_with_repeat():
    now = datetime(2026, 1, 30, 10, 0)
    parsed = parse_reminder("1 февраля в 14:30 стоматолог /every month", now)
    assert parsed is not None
    assert parsed.text == "стоматолог"
    assert parsed.repeat_rule == "month"
    assert parsed.when_local == datetime(2026, 2, 1, 14, 30)


def test_parse_when_only():
    now = datetime(2026, 1, 30, 10, 0)
    parsed = parse_when_only("завтра в 9 утра", now)
    assert parsed == datetime(2026, 1, 31, 9, 0)


def test_parse_natural_reminder_prefix_and_evening():
    now = datetime(2026, 1, 30, 10, 0)
    parsed = parse_reminder("напомни вечером оплатить счет", now)
    assert parsed is not None
    assert parsed.text == "оплатить счет"
    assert parsed.when_local == datetime(2026, 1, 30, 19, 0)


def test_parse_spoken_evening_time_with_filler_words():
    now = datetime(2026, 1, 30, 10, 0)
    parsed = parse_reminder("напомни в 7 часов вечера что оплатить счет", now)
    assert parsed is not None
    assert parsed.text == "оплатить счет"
    assert parsed.when_local == datetime(2026, 1, 30, 19, 0)


def test_parse_tomorrow_morning_part_of_day():
    now = datetime(2026, 1, 30, 20, 0)
    parsed = parse_reminder("завтра утром зарядка", now)
    assert parsed is not None
    assert parsed.text == "зарядка"
    assert parsed.when_local == datetime(2026, 1, 31, 9, 0)


def test_parse_relative_hours_natural_phrase():
    now = datetime(2026, 1, 30, 10, 0)
    parsed = parse_reminder("через 2 часа проверить счет", now)
    assert parsed is not None
    assert parsed.text == "проверить счет"
    assert parsed.when_local == datetime(2026, 1, 30, 12, 0)


def test_parse_duration():
    assert parse_duration_to_timedelta("90").total_seconds() == 5400
    assert parse_duration_to_timedelta("2ч").total_seconds() == 7200


def test_next_repeat_month_caps_day():
    dt = datetime(2026, 1, 31, 9, 0)
    assert next_repeat_time(dt, "month") == datetime(2026, 2, 28, 9, 0)
