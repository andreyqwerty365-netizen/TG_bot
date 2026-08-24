from __future__ import annotations

from ..db import Database
from ..utils.date_utils import fmt_ru_date_time


def search_records(db: Database, chat_id: int, needle: str):
    notes = db.search_notes(chat_id, needle, archived=False, limit=10)
    reminders = db.search_reminders(chat_id, needle, archived=False, include_done=True, limit=10)
    return notes, reminders


def build_search_text(db: Database, chat_id: int, needle: str, *, notes=None, reminders=None) -> str:
    if notes is None or reminders is None:
        notes, reminders = search_records(db, chat_id, needle)
    tz_offset = db.get_chat_settings(chat_id).tz_offset_minutes

    lines = [f"🔎 Поиск: {needle}", ""]
    if notes:
        lines.append("📝 Заметки:")
        for idx, note in enumerate(notes, 1):
            lines.append(f"{idx}) {note.text}")
        lines.append("")
    else:
        lines.append("📝 Заметки: ничего не найдено")
        lines.append("")

    if reminders:
        lines.append("⏰ Напоминания:")
        for idx, reminder in enumerate(reminders, 1):
            lines.append(f"{idx}) {fmt_ru_date_time(reminder.remind_at, tz_offset)} — {reminder.text}")
    else:
        lines.append("⏰ Напоминания: ничего не найдено")
    return "\n".join(lines)
