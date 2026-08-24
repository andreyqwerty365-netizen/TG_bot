from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta


RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
RU_TIME_KEYWORDS = {"полдень": (12, 0), "полночь": (0, 0)}
RU_WEEKDAYS = {
    "понедельник": 1,
    "пн": 1,
    "вторник": 2,
    "вт": 2,
    "среда": 3,
    "ср": 3,
    "четверг": 4,
    "чт": 4,
    "пятница": 5,
    "пт": 5,
    "суббота": 6,
    "сб": 6,
    "воскресенье": 7,
    "вс": 7,
}

PART_OF_DAY_TIMES = {
    "утром": (9, 0),
    "утро": (9, 0),
    "днём": (13, 0),
    "днем": (13, 0),
    "день": (13, 0),
    "вечером": (19, 0),
    "вечер": (19, 0),
    "ночью": (22, 0),
    "ночь": (22, 0),
}


@dataclass(slots=True)
class ParsedReminder:
    when_local: datetime
    text: str
    repeat_rule: str | None = None


def _parse_hhmm(text: str) -> tuple[int, int] | None:
    text = text.strip().lower()
    if text in RU_TIME_KEYWORDS:
        return RU_TIME_KEYWORDS[text]
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text)
    if not match:
        return None
    hh = int(match.group(1))
    mm = int(match.group(2) or "0")
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh, mm
    return None


def _parse_time_words(tokens: list[str]) -> tuple[int, int] | None:
    if not tokens:
        return None
    parsed = _parse_hhmm(tokens[0])
    if not parsed:
        return None
    hh, mm = parsed
    if len(tokens) == 1:
        return hh, mm
    marker = tokens[1].lower()
    if marker in {"утра", "утром"}:
        if hh == 12:
            hh = 0
        return (hh, mm) if hh <= 11 else None
    if marker in {"вечера", "вечером"}:
        if hh == 12:
            return 12, mm
        if 1 <= hh <= 11:
            return hh + 12, mm
        if 13 <= hh <= 23:
            return hh, mm
        return None
    if marker == "дня":
        if 1 <= hh <= 11:
            return hh + 12, mm
        return hh, mm
    if marker == "ночи":
        if hh == 12:
            hh = 0
        return (hh, mm) if hh <= 5 else None
    return hh, mm


def _next_weekday(from_date: date, target: int) -> date:
    delta = (target - from_date.isoweekday()) % 7
    if delta == 0:
        delta = 7
    return from_date + timedelta(days=delta)


def parse_duration_to_timedelta(raw: str) -> timedelta | None:
    s = (raw or "").strip().lower()
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return timedelta(minutes=int(s))
    patterns = [
        (r"(\d+)\s*(с|сек|секунд|секунда|секунды)", "seconds"),
        (r"(\d+)\s*(м|m|мин|минута|минут|минуты)", "minutes"),
        (r"(\d+)\s*(ч|h|час|часа|часов)", "hours"),
        (r"(\d+)\s*(д|день|дня|дней)", "days"),
    ]
    for pattern, unit in patterns:
        match = re.fullmatch(pattern, s)
        if match:
            return timedelta(**{unit: int(match.group(1))})
    return None


def parse_when_only(text: str, now_local: datetime) -> datetime | None:
    parsed = parse_reminder(f"{text} ___", now_local)
    return parsed.when_local if parsed else None


def _strip_reminder_prefix(src: str) -> str:
    return re.sub(
        r"^(?:дружище[,!\s]+)?(?:пожалуйста[,!\s]+)?(?:напомни(?:\s+мне)?|напомнить)\s+",
        "",
        src,
        flags=re.IGNORECASE,
    ).strip()


def _normalize_spoken_time(src: str) -> str:
    return re.sub(
        r"\b(\d{1,2})(?::(\d{2}))?\s+(?:час|часа|часов)\s+(утра|утром|вечера|вечером|дня|ночи)\b",
        lambda m: f"{m.group(1)}{':' + m.group(2) if m.group(2) else ''} {m.group(3)}",
        src,
        flags=re.IGNORECASE,
    )


def _part_of_day_dt(day_word: str | None, part_word: str, now_local: datetime) -> datetime:
    hh, mm = PART_OF_DAY_TIMES[part_word]
    base = now_local.date()
    if day_word == "завтра":
        base += timedelta(days=1)
    elif day_word == "послезавтра":
        base += timedelta(days=2)
    dt = datetime(base.year, base.month, base.day, hh, mm)
    if day_word in (None, "сегодня") and dt <= now_local:
        dt += timedelta(days=1)
    return dt


def parse_reminder(text: str, now_local: datetime) -> ParsedReminder | None:
    src = " ".join((text or "").strip().split())
    if not src:
        return None
    src = _normalize_spoken_time(_strip_reminder_prefix(src))
    if not src:
        return None
    lowered = src.lower()

    repeat_rule = None
    repeat_match = re.search(r"\s+/every\s+(day|week|month)\s*$", lowered)
    if repeat_match:
        repeat_rule = repeat_match.group(1)
        lowered = lowered[: repeat_match.start()].strip()
        src = src[: repeat_match.start()].strip()

    def out(dt: datetime, message: str) -> ParsedReminder | None:
        message = message.strip()
        message = re.sub(r"^(?:что|чтобы)\s+", "", message, flags=re.IGNORECASE).strip()
        if not message:
            return None
        return ParsedReminder(when_local=dt, text=message, repeat_rule=repeat_rule)

    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s+(?:в\s+)?(\d{1,2}:\d{2})\s+(.+)$", lowered)
    if match:
        hhmm = _parse_hhmm(match.group(4))
        if not hhmm:
            return None
        hh, mm = hhmm
        try:
            return out(datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), hh, mm), src[src.lower().find(match.group(5)):])
        except ValueError:
            return None

    match = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\s+(?:в\s+)?(\d{1,2}:\d{2}|\d{1,2})\s+(.+)$", lowered)
    if match:
        year_raw = match.group(3)
        year = int(year_raw) + (2000 if year_raw and len(year_raw) == 2 else 0) if year_raw else now_local.year
        parsed = _parse_time_words([match.group(4)])
        if not parsed:
            return None
        hh, mm = parsed
        try:
            dt = datetime(year, int(match.group(2)), int(match.group(1)), hh, mm)
        except ValueError:
            return None
        if not year_raw and dt < now_local:
            dt = datetime(year + 1, int(match.group(2)), int(match.group(1)), hh, mm)
        return out(dt, src[src.lower().find(match.group(5)):])

    match = re.match(r"^через\s+(полчаса|час|сутки)\s+(.+)$", lowered)
    if match:
        delta = {"полчаса": timedelta(minutes=30), "час": timedelta(hours=1), "сутки": timedelta(days=1)}[match.group(1)]
        return out(now_local + delta, src[src.lower().find(match.group(2)):])

    match = re.match(r"^(\d+)\s*(м|мин|минута|минут|минуты|m|ч|час|часа|часов|h|д|день|дня|дней|н|нед|неделя|недель|недели)\b\s+(.+)$", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit.startswith(("м", "m")):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("ч", "h")):
            delta = timedelta(hours=amount)
        elif unit.startswith("н"):
            delta = timedelta(weeks=amount)
        else:
            delta = timedelta(days=amount)
        return out(now_local + delta, src[src.lower().find(match.group(3)):])

    match = re.match(r"^через\s+(\d+)\s+(м|мин|минута|минут|минуты|m|ч|час|часа|часов|h|д|день|дня|дней|н|нед|неделя|недель|недели)(?:\s+в\s+(.+?))?\s+(.+)$", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        time_part = (match.group(3) or "").strip()
        if unit.startswith(("м", "m")):
            return out(now_local + timedelta(minutes=amount), src[src.lower().find(match.group(4)):])
        if unit.startswith(("ч", "h")):
            return out(now_local + timedelta(hours=amount), src[src.lower().find(match.group(4)):])
        base_date = now_local.date() + (timedelta(days=amount) if unit.startswith("д") else timedelta(weeks=amount))
        if time_part:
            parsed = _parse_time_words(time_part.split())
            if not parsed:
                return None
            hh, mm = parsed
            return out(datetime(base_date.year, base_date.month, base_date.day, hh, mm), src[src.lower().find(match.group(4)):])
        return out(now_local + (timedelta(days=amount) if unit.startswith("д") else timedelta(weeks=amount)), src[src.lower().find(match.group(4)):])

    part_pattern = "|".join(sorted(PART_OF_DAY_TIMES, key=len, reverse=True))
    match = re.match(rf"^(?:(сегодня|завтра|послезавтра)\s+)?({part_pattern})\s+(.+)$", lowered)
    if match:
        return out(_part_of_day_dt(match.group(1), match.group(2), now_local), src[src.lower().find(match.group(3)):])

    time_pattern = r"((?:полдень|полночь|\d{1,2}(?::\d{2})?)(?:\s+(?:утра|утром|вечера|вечером|дня|ночи))?)"

    match = re.match(rf"^(сегодня|завтра|послезавтра)\s+(?:в\s+)?{time_pattern}\s+(.+)$", lowered)
    if match:
        parsed = _parse_time_words(match.group(2).split())
        if not parsed:
            return None
        hh, mm = parsed
        base = now_local.date()
        if match.group(1) == "завтра":
            base += timedelta(days=1)
        elif match.group(1) == "послезавтра":
            base += timedelta(days=2)
        return out(datetime(base.year, base.month, base.day, hh, mm), src[src.lower().find(match.group(3)):])

    match = re.match(rf"^в\s+([а-яё]+)\s+(?:в\s+)?{time_pattern}\s+(.+)$", lowered)
    if match and match.group(1) in RU_WEEKDAYS:
        parsed = _parse_time_words(match.group(2).split())
        if not parsed:
            return None
        hh, mm = parsed
        base = _next_weekday(now_local.date(), RU_WEEKDAYS[match.group(1)])
        return out(datetime(base.year, base.month, base.day, hh, mm), src[src.lower().find(match.group(3)):])

    match = re.match(rf"^в\s+{time_pattern}\s+(.+)$", lowered)
    if match:
        parsed = _parse_time_words(match.group(1).split())
        if parsed:
            hh, mm = parsed
            base = now_local.date()
            dt = datetime(base.year, base.month, base.day, hh, mm)
            if dt <= now_local:
                dt += timedelta(days=1)
            return out(dt, src[src.lower().find(match.group(2)):])

    match = re.match(rf"^(\d{{1,2}})\s+([а-яё]+)\s+(?:в\s+)?{time_pattern}\s+(.+)$", lowered)
    if match and match.group(2) in RU_MONTHS:
        parsed = _parse_time_words(match.group(3).split())
        if not parsed:
            return None
        hh, mm = parsed
        year = now_local.year
        try:
            dt = datetime(year, RU_MONTHS[match.group(2)], int(match.group(1)), hh, mm)
        except ValueError:
            return None
        if dt < now_local:
            dt = datetime(year + 1, RU_MONTHS[match.group(2)], int(match.group(1)), hh, mm)
        return out(dt, src[src.lower().find(match.group(4)):])

    match = re.match(r"^через\s+(минуту|минуты|минут|полминуты)\s+(.+)$", lowered)
    if match:
        delta = timedelta(seconds=30 if match.group(1) == "полминуты" else 60)
        return out(now_local + delta, src[src.lower().find(match.group(2)):])

    return None


def next_repeat_time(remind_at_local: datetime, repeat_rule: str) -> datetime:
    repeat_rule = repeat_rule.lower().strip()
    if repeat_rule == "day":
        return remind_at_local + timedelta(days=1)
    if repeat_rule == "week":
        return remind_at_local + timedelta(weeks=1)
    if repeat_rule == "month":
        month = remind_at_local.month + 1
        year = remind_at_local.year
        if month == 13:
            month = 1
            year += 1
        month_lengths = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        day = min(remind_at_local.day, month_lengths[month - 1])
        return remind_at_local.replace(year=year, month=month, day=day)
    raise ValueError(f"Unsupported repeat rule: {repeat_rule}")
