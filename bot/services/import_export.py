from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from ..db import Database
from ..models import Reminder
from ..utils.date_utils import iso_utc, parse_iso_utc, utc_now

MAX_IMPORT_FILE_BYTES = 5 * 1024 * 1024
MAX_IMPORT_RECORDS = 10_000
MAX_RECORD_TEXT_CHARS = 10_000
ALLOWED_REPEAT_RULES = {None, "day", "week", "month"}


@dataclass(slots=True)
class ImportResult:
    imported_notes: int
    imported_archived_notes: int
    imported_reminders: int
    imported_archived_reminders: int
    skipped_duplicates: int
    scheduled_reminder_ids: list[int]


@dataclass(slots=True)
class PreparedImport:
    tz_offset_minutes: int
    dayplan_enabled: bool
    dayplan_time: str | None
    active_notes: list[dict[str, Any]]
    archived_notes: list[dict[str, Any]]
    reminders: list[tuple[dict[str, Any], bool]]


def build_export_payload(db: Database, chat_id: int) -> dict[str, Any]:
    settings = db.get_chat_settings(chat_id)
    query_limit = MAX_IMPORT_RECORDS + 1
    notes_active = db.list_notes(chat_id, archived=False, limit=query_limit)
    notes_archived = db.list_notes(chat_id, archived=True, limit=query_limit)
    reminders_active = db.list_reminders(chat_id, archived=False, include_done=True, limit=query_limit)
    reminders_archived = db.list_reminders(chat_id, archived=True, include_done=True, limit=query_limit)
    total_records = len(notes_active) + len(notes_archived) + len(reminders_active) + len(reminders_archived)
    if total_records > MAX_IMPORT_RECORDS:
        raise ValueError(f"Экспорт содержит больше {MAX_IMPORT_RECORDS} записей.")
    return {
        "version": 5,
        "exported_at_utc": iso_utc(utc_now()),
        "tz_offset_minutes": settings.tz_offset_minutes,
        "dayplan_enabled": settings.dayplan_enabled,
        "dayplan_time": settings.dayplan_time,
        "notes": {
            "active": [{"text": note.text, "created_at": iso_utc(note.created_at)} for note in notes_active],
            "archived": [{"text": note.text, "created_at": iso_utc(note.created_at)} for note in notes_archived],
        },
        "reminders": {
            "active": [_reminder_json(reminder) for reminder in reminders_active],
            "archived": [_reminder_json(reminder) for reminder in reminders_archived],
        },
    }


def import_payload(db: Database, chat_id: int, payload: dict[str, Any]) -> ImportResult:
    prepared = prepare_import_payload(db, chat_id, payload)

    existing_active_notes = {_normalize_note_key(note.text) for note in db.list_notes(chat_id, archived=False, limit=100000)}
    existing_archived_notes = {_normalize_note_key(note.text) for note in db.list_notes(chat_id, archived=True, limit=100000)}
    existing_active_reminders = {_reminder_identity(rem) for rem in db.list_reminders(chat_id, archived=False, include_done=True, limit=100000)}
    existing_archived_reminders = {_reminder_identity(rem) for rem in db.list_reminders(chat_id, archived=True, include_done=True, limit=100000)}

    imported_notes = imported_archived_notes = 0
    imported_reminders = imported_archived_reminders = 0
    skipped_duplicates = 0
    scheduled_reminder_ids: list[int] = []

    with db.connect() as conn:
        _upsert_settings(conn, chat_id, prepared)

        for item in prepared.active_notes:
            key = _normalize_note_key(item["text"])
            if key in existing_active_notes:
                skipped_duplicates += 1
                continue
            _insert_note(conn, chat_id, item, archived=False)
            existing_active_notes.add(key)
            imported_notes += 1

        for item in prepared.archived_notes:
            key = _normalize_note_key(item["text"])
            if key in existing_archived_notes:
                skipped_duplicates += 1
                continue
            _insert_note(conn, chat_id, item, archived=True)
            existing_archived_notes.add(key)
            imported_archived_notes += 1

        for item, archived in prepared.reminders:
            key = _reminder_payload_identity(item)
            existing_bucket = existing_archived_reminders if archived else existing_active_reminders
            if key in existing_bucket:
                skipped_duplicates += 1
                continue

            reminder_id = _insert_reminder(conn, chat_id, item, archived=archived)
            existing_bucket.add(key)
            if archived:
                imported_archived_reminders += 1
            else:
                imported_reminders += 1
                if not item.get("done_at"):
                    scheduled_reminder_ids.append(reminder_id)

    return ImportResult(
        imported_notes=imported_notes,
        imported_archived_notes=imported_archived_notes,
        imported_reminders=imported_reminders,
        imported_archived_reminders=imported_archived_reminders,
        skipped_duplicates=skipped_duplicates,
        scheduled_reminder_ids=scheduled_reminder_ids,
    )


def prepare_import_payload(db: Database, chat_id: int, payload: dict[str, Any]) -> PreparedImport:
    if not isinstance(payload, dict):
        raise ValueError("Корневой элемент JSON должен быть объектом.")

    current_settings = db.get_chat_settings(chat_id)
    tz = _parse_timezone(payload.get("tz_offset_minutes", current_settings.tz_offset_minutes))
    dayplan_enabled = payload.get("dayplan_enabled", current_settings.dayplan_enabled)
    if not isinstance(dayplan_enabled, bool):
        raise ValueError("dayplan_enabled должен быть true или false.")
    dayplan_time = payload.get("dayplan_time", current_settings.dayplan_time)
    if dayplan_time is not None:
        if not isinstance(dayplan_time, str) or not _is_valid_hhmm(dayplan_time):
            raise ValueError("dayplan_time должен иметь формат HH:MM.")
    if dayplan_enabled and dayplan_time is None:
        raise ValueError("Для включённого плана дня требуется dayplan_time.")

    notes_section = payload.get("notes") or {}
    reminders_section = payload.get("reminders") or {}
    if not isinstance(notes_section, dict):
        raise ValueError("Раздел notes должен быть объектом.")
    if not isinstance(reminders_section, dict):
        raise ValueError("Раздел reminders должен быть объектом.")

    active_notes = [_normalize_note_item(item) for item in _iter_notes(notes_section.get("active", []))]
    archived_notes = [_normalize_note_item(item) for item in _iter_notes(notes_section.get("archived", []))]
    reminders = [(_normalize_reminder_item(item), archived) for item, archived in _iter_reminders(reminders_section)]

    total_records = len(active_notes) + len(archived_notes) + len(reminders)
    if total_records > MAX_IMPORT_RECORDS:
        raise ValueError(f"Импорт содержит больше {MAX_IMPORT_RECORDS} записей.")

    return PreparedImport(
        tz_offset_minutes=tz,
        dayplan_enabled=dayplan_enabled,
        dayplan_time=dayplan_time,
        active_notes=active_notes,
        archived_notes=archived_notes,
        reminders=reminders,
    )


def _iter_notes(items: Any):
    if not isinstance(items, list):
        raise ValueError("Список заметок должен быть массивом.")
    for item in items:
        if isinstance(item, dict):
            text = _required_text(item.get("text"), "Текст заметки")
            created_at = _optional_text(item.get("created_at"), "created_at")
        elif isinstance(item, str):
            text = _required_text(item, "Текст заметки")
            created_at = None
        else:
            raise ValueError("Каждая заметка должна быть строкой или объектом.")
        yield {"text": text, "created_at": created_at}


def _iter_reminders(reminders_section: Any):
    for section_name, archived in (("active", False), ("archived", True)):
        items = reminders_section.get(section_name, [])
        if not isinstance(items, list):
            raise ValueError("Список напоминаний должен быть массивом.")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Каждое напоминание должно быть объектом.")
            text = _required_text(item.get("text"), "Текст напоминания")
            remind_at = _required_text(item.get("remind_at"), "remind_at")
            yield {
                "text": text,
                "remind_at": remind_at,
                "repeat_rule": (item.get("repeat_rule") or None),
                "done_at": (item.get("done_at") or None),
                "created_at": (item.get("created_at") or None),
            }, archived


def _upsert_settings(conn: sqlite3.Connection, chat_id: int, prepared: PreparedImport) -> None:
    conn.execute(
        """
        INSERT INTO chat_settings(chat_id, tz_offset_minutes, dayplan_enabled, dayplan_time)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            tz_offset_minutes=excluded.tz_offset_minutes,
            dayplan_enabled=excluded.dayplan_enabled,
            dayplan_time=excluded.dayplan_time
        """,
        (chat_id, prepared.tz_offset_minutes, 1 if prepared.dayplan_enabled else 0, prepared.dayplan_time),
    )


def _insert_note(conn: sqlite3.Connection, chat_id: int, item: dict[str, Any], *, archived: bool) -> int:
    created_at = item.get("created_at") or iso_utc(utc_now())
    cursor = conn.execute(
        "INSERT INTO notes(chat_id, text, created_at, is_archived) VALUES (?, ?, ?, ?)",
        (chat_id, item["text"], created_at, 1 if archived else 0),
    )
    return int(cursor.lastrowid)


def _insert_reminder(conn: sqlite3.Connection, chat_id: int, item: dict[str, Any], *, archived: bool) -> int:
    created_at = item.get("created_at") or iso_utc(utc_now())
    cursor = conn.execute(
        """
        INSERT INTO reminders(chat_id, text, remind_at, repeat_rule, is_archived, done_at, created_at, job_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (chat_id, item["text"], item["remind_at"], item.get("repeat_rule"), 1 if archived else 0, item.get("done_at"), created_at),
    )
    reminder_id = int(cursor.lastrowid)
    conn.execute("UPDATE reminders SET job_name=? WHERE id=?", (f"reminder:{reminder_id}", reminder_id))
    return reminder_id


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} должен быть непустой строкой.")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} должен быть строкой.")
    return value.strip() or None


def _normalize_note_item(item: dict[str, Any]) -> dict[str, Any]:
    _validate_record_text(item["text"])
    created_at = _normalize_optional_datetime(item.get("created_at"))
    return {"text": item["text"], "created_at": created_at}


def _normalize_reminder_item(item: dict[str, Any]) -> dict[str, Any]:
    _validate_record_text(item["text"])
    repeat_rule = item.get("repeat_rule") or None
    if repeat_rule not in ALLOWED_REPEAT_RULES:
        raise ValueError(f"Неподдерживаемый repeat_rule: {repeat_rule}")
    return {
        "text": item["text"],
        "remind_at": iso_utc(parse_iso_utc(item["remind_at"])),
        "repeat_rule": repeat_rule,
        "done_at": _normalize_optional_datetime(item.get("done_at")),
        "created_at": _normalize_optional_datetime(item.get("created_at")),
    }


def _normalize_optional_datetime(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("Дата в импорте должна быть строкой ISO 8601.")
    return iso_utc(parse_iso_utc(value))


def _parse_timezone(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("tz_offset_minutes должен быть целым числом.")
    try:
        tz = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("tz_offset_minutes должен быть целым числом.") from exc
    if not -14 * 60 <= tz <= 14 * 60:
        raise ValueError("tz_offset_minutes должен быть в диапазоне от -840 до 840.")
    return tz


def _is_valid_hhmm(value: str) -> bool:
    try:
        hh, mm = map(int, value.split(":"))
    except ValueError:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59


def _validate_record_text(text: str) -> None:
    if len(text) > MAX_RECORD_TEXT_CHARS:
        raise ValueError(f"Текст записи длиннее {MAX_RECORD_TEXT_CHARS} символов.")


def _normalize_note_key(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _reminder_identity(reminder: Reminder) -> tuple[str, str, str | None, bool]:
    return (
        _normalize_note_key(reminder.text),
        iso_utc(reminder.remind_at),
        reminder.repeat_rule or None,
        reminder.done_at is not None,
    )


def _reminder_payload_identity(item: dict[str, Any]) -> tuple[str, str, str | None, bool]:
    return (
        _normalize_note_key(item["text"]),
        item["remind_at"],
        item.get("repeat_rule") or None,
        bool(item.get("done_at")),
    )


def _reminder_json(reminder: Reminder) -> dict[str, Any]:
    return {
        "text": reminder.text,
        "remind_at": iso_utc(reminder.remind_at),
        "repeat_rule": reminder.repeat_rule,
        "done_at": iso_utc(reminder.done_at) if reminder.done_at else None,
        "created_at": iso_utc(reminder.created_at),
    }
