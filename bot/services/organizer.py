from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..db import Database
from ..services.reminder_parser_ru import ParsedReminder, parse_reminder, parse_when_only
from ..utils.date_utils import fmt_ru_date_or_time, fmt_ru_date_time, local_to_utc, to_local, utc_now
from ..views import build_last_text


@dataclass(slots=True)
class CaptureResult:
    kind: str
    text: str
    note_id: int | None = None
    reminder_id: int | None = None
    remind_at_utc: datetime | None = None
    repeat_rule: str | None = None


def build_today_plan(db: Database, chat_id: int) -> str:
    settings = db.get_chat_settings(chat_id)
    now_local = to_local(utc_now(), settings.tz_offset_minutes)
    reminders = db.list_reminders(chat_id, archived=False, include_done=False, limit=1000)

    overdue = []
    today = []
    for reminder in reminders:
        local_dt = to_local(reminder.remind_at, settings.tz_offset_minutes)
        if local_dt < now_local:
            overdue.append(reminder)
        elif local_dt.date() == now_local.date():
            today.append(reminder)

    lines = ["📅 Сегодня", ""]
    if overdue:
        lines.append("⚠️ Просрочено:")
        for idx, reminder in enumerate(sorted(overdue, key=lambda item: item.remind_at), 1):
            lines.append(f"{idx}) {to_local(reminder.remind_at, settings.tz_offset_minutes):%H:%M} — {reminder.text}")
    else:
        lines.append("⚠️ Просрочено:\n(нет)")

    lines.append("")
    if today:
        lines.append("✅ Сегодня:")
        for idx, reminder in enumerate(sorted(today, key=lambda item: item.remind_at), 1):
            lines.append(f"{idx}) {to_local(reminder.remind_at, settings.tz_offset_minutes):%H:%M} — {reminder.text}")
    else:
        lines.append("✅ Сегодня:\n(нет)")

    return "\n".join(lines)


def build_next_reminder_text(db: Database, chat_id: int) -> str:
    settings = db.get_chat_settings(chat_id)
    reminders = db.list_reminders(chat_id, archived=False, include_done=False, limit=200)
    if not reminders:
        return "📌 Ближайшее напоминание:\n(пока нет активных напоминаний)"
    reminder = min(reminders, key=lambda item: item.remind_at)
    return (
        "📌 Ближайшее напоминание:\n"
        f"{fmt_ru_date_time(reminder.remind_at, settings.tz_offset_minutes)}\n"
        f"{reminder.text}"
    )


def build_tomorrow_plan(db: Database, chat_id: int) -> str:
    settings = db.get_chat_settings(chat_id)
    now_local = to_local(utc_now(), settings.tz_offset_minutes)
    tomorrow = now_local.date() + timedelta(days=1)
    reminders = db.list_reminders(chat_id, archived=False, include_done=False, limit=1000)
    tomorrow_items = []
    for reminder in reminders:
        local_dt = to_local(reminder.remind_at, settings.tz_offset_minutes)
        if local_dt.date() == tomorrow:
            tomorrow_items.append(reminder)

    if not tomorrow_items:
        return "📆 Завтра:\n(пока нет напоминаний)"

    lines = ["📆 Завтра:", ""]
    for idx, reminder in enumerate(sorted(tomorrow_items, key=lambda item: item.remind_at), 1):
        lines.append(f"{idx}) {to_local(reminder.remind_at, settings.tz_offset_minutes):%H:%M} — {reminder.text}")
    return "\n".join(lines)


def build_overdue_reminders_text(db: Database, chat_id: int) -> str:
    settings = db.get_chat_settings(chat_id)
    now_local = to_local(utc_now(), settings.tz_offset_minutes)
    reminders = db.list_reminders(chat_id, archived=False, include_done=False, limit=500)
    overdue = [reminder for reminder in reminders if to_local(reminder.remind_at, settings.tz_offset_minutes) < now_local]
    if not overdue:
        return "⚠️ Просроченные:\n(нет)"
    lines = ["⚠️ Просроченные:", ""]
    for idx, reminder in enumerate(sorted(overdue, key=lambda item: item.remind_at), 1):
        lines.append(f"{idx}) {fmt_ru_date_or_time(reminder.remind_at, settings.tz_offset_minutes)} — {reminder.text}")
    return "\n".join(lines)


def cleanup_completed_reminders(db: Database, chat_id: int) -> int:
    return db.archive_completed_reminders(chat_id)


def build_last_screen(db: Database, chat_id: int) -> str:
    tz_offset = db.get_chat_settings(chat_id).tz_offset_minutes
    notes = db.list_notes(chat_id, archived=False, limit=5)
    reminders = db.list_reminders(chat_id, archived=False, include_done=False, limit=5)
    return build_last_text(notes, reminders, tz_offset)


def build_stats_text(db: Database, chat_id: int) -> str:
    settings = db.get_chat_settings(chat_id)
    notes_count = db.count_notes(chat_id, archived=False)
    notes_archived_count = db.count_notes(chat_id, archived=True)
    reminders_count = db.count_reminders(chat_id, archived=False, include_done=True)
    pending_count = db.count_reminders(chat_id, archived=False, include_done=False)
    done_count = reminders_count - pending_count
    reminders_archived_count = db.count_reminders(chat_id, archived=True, include_done=True)

    return (
        "📊 Статистика:\n"
        f"- заметки: {notes_count} активных / {notes_archived_count} в архиве\n"
        f"- напоминания: {pending_count} активных / {done_count} выполненных / {reminders_archived_count} в архиве\n"
        f"- таймзона: UTC{settings.tz_offset_minutes / 60:+g}\n"
        f"- план дня: {'включён' if settings.dayplan_enabled else 'выключен'}"
    )


def build_saved_reminder_text(reminder: ParsedReminder, remind_at_utc: datetime, tz_offset_minutes: int) -> str:
    repeat = f"\nПовтор: {reminder.repeat_rule}" if reminder.repeat_rule else ""
    return f"✅ Напоминание сохранено:\n{fmt_ru_date_time(remind_at_utc, tz_offset_minutes)}\n{reminder.text}{repeat}"


def build_capture_success_text(remind_at_utc: datetime, tz_offset_minutes: int, text: str) -> str:
    return f"✅ Напоминание создано:\n{fmt_ru_date_time(remind_at_utc, tz_offset_minutes)}\n{text}"


def create_reminder_from_text(db: Database, chat_id: int, text: str) -> tuple[ParsedReminder | None, datetime | None]:
    settings = db.get_chat_settings(chat_id)
    parsed = parse_reminder(text, to_local(utc_now(), settings.tz_offset_minutes).replace(tzinfo=None))
    if not parsed:
        return None, None
    remind_at_utc = local_to_utc(parsed.when_local, settings.tz_offset_minutes)
    return parsed, remind_at_utc


def smart_capture(db: Database, chat_id: int, text: str) -> CaptureResult:
    parsed, remind_at_utc = create_reminder_from_text(db, chat_id, text)
    if parsed and remind_at_utc is not None:
        reminder_id = db.add_reminder(chat_id, parsed.text, remind_at_utc, parsed.repeat_rule)
        return CaptureResult(
            kind="reminder",
            text=parsed.text,
            reminder_id=reminder_id,
            remind_at_utc=remind_at_utc,
            repeat_rule=parsed.repeat_rule,
        )

    note_id = db.add_note(chat_id, text)
    return CaptureResult(kind="note", text=text, note_id=note_id)


def create_preset_reminder(db: Database, chat_id: int, text: str, minutes: int) -> CaptureResult:
    remind_at_utc = utc_now() + timedelta(minutes=minutes)
    reminder_id = db.add_reminder(chat_id, text, remind_at_utc)
    return CaptureResult(kind="reminder", text=text, reminder_id=reminder_id, remind_at_utc=remind_at_utc)


def parse_when_text(db: Database, chat_id: int, text: str) -> datetime | None:
    settings = db.get_chat_settings(chat_id)
    return parse_when_only(text, to_local(utc_now(), settings.tz_offset_minutes).replace(tzinfo=None))


def parse_tz_offset(raw: str) -> int | None:
    raw = raw.strip()
    try:
        if ":" in raw:
            sign = -1 if raw.startswith("-") else 1
            raw_clean = raw[1:] if raw[:1] in "+-" else raw
            hh, mm = raw_clean.split(":", 1)
            total = sign * (int(hh) * 60 + int(mm))
        else:
            total = int(raw) * 60
    except Exception:
        return None
    return total if -14 * 60 <= total <= 14 * 60 else None


def is_valid_hhmm(raw: str) -> bool:
    try:
        hh, mm = map(int, raw.split(":"))
    except Exception:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59


def format_quick_reminder_confirmation(remind_at_utc: datetime, tz_offset_minutes: int, text: str) -> str:
    return f"✅ {fmt_ru_date_or_time(remind_at_utc, tz_offset_minutes)} — {text}"
