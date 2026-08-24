from __future__ import annotations

from datetime import UTC, datetime, timedelta

RU_MONTH_GEN = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_utc(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_local(dt_utc: datetime, tz_offset_minutes: int) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC)
    return dt_utc.astimezone(UTC) + timedelta(minutes=tz_offset_minutes)


def local_to_utc(dt_local: datetime, tz_offset_minutes: int) -> datetime:
    if dt_local.tzinfo is not None:
        dt_local = dt_local.replace(tzinfo=None)
    return (dt_local - timedelta(minutes=tz_offset_minutes)).replace(tzinfo=UTC)


def fmt_ru_date_time(dt_utc: datetime, tz_offset_minutes: int, show_year: bool = False) -> str:
    dt = to_local(dt_utc, tz_offset_minutes)
    month = RU_MONTH_GEN.get(dt.month, str(dt.month))
    if show_year:
        return f"{dt.day} {month} {dt.year} в {dt:%H:%M}"
    return f"{dt.day} {month} в {dt:%H:%M}"


def fmt_ru_date_or_time(dt_utc: datetime, tz_offset_minutes: int, *, now_utc: datetime | None = None) -> str:
    dt = to_local(dt_utc, tz_offset_minutes)
    now_local = to_local(now_utc or utc_now(), tz_offset_minutes)
    if dt.date() == now_local.date():
        return dt.strftime("%H:%M")
    same_year = dt.year == now_local.year
    month = RU_MONTH_GEN.get(dt.month, str(dt.month))
    if same_year:
        return f"{dt.day} {month} {dt:%H:%M}"
    return f"{dt.day} {month} {dt.year} {dt:%H:%M}"
