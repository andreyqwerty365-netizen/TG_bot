from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from bot.db import Database


def test_db_crud_and_search(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    note_id = db.add_note(1, "Купить воду и чай")
    remind_at = datetime(2026, 1, 30, 12, 0, tzinfo=UTC)
    reminder_id = db.add_reminder(1, "Купить воду", remind_at, "day")

    assert db.get_note(1, note_id) is not None
    assert db.get_reminder(1, reminder_id) is not None

    notes = db.search_notes(1, "воду")
    reminders = db.search_reminders(1, "воду")
    assert len(notes) == 1
    assert len(reminders) == 1

    assert db.update_note(1, note_id, "Купить кофе")
    assert db.update_reminder_text(1, reminder_id, "Купить кофе")
    assert db.search_notes(1, "кофе")
    assert db.search_reminders(1, "кофе")


def test_db_pagination_and_online_backup(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    for idx in range(12):
        db.add_note(1, f"Заметка {idx}")

    assert db.count_notes(1) == 12
    assert len(db.list_notes(1, limit=10, offset=0)) == 10
    assert len(db.list_notes(1, limit=10, offset=10)) == 2

    backup_path = tmp_path / "backups" / "notes.db"
    db.backup_to(backup_path)
    restored = Database(backup_path)
    restored.init()
    assert restored.count_notes(1) == 12


def test_db_init_migrates_legacy_schema_before_creating_indexes(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL
            );
            CREATE TABLE chat_settings (
                chat_id INTEGER PRIMARY KEY,
                tz_offset_minutes INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO notes(chat_id, text, created_at)
                VALUES (7, 'Старая заметка', '2026-01-01T09:00:00+00:00');
            INSERT INTO reminders(chat_id, text, remind_at)
                VALUES (7, 'Старое напоминание', '2026-01-02T09:00:00+00:00');
            INSERT INTO chat_settings(chat_id, tz_offset_minutes)
                VALUES (7, 180);
            """
        )

    db = Database(db_path)
    db.init()

    assert db.get_note(7, 1) is not None
    reminder = db.get_reminder(7, 1)
    assert reminder is not None
    assert reminder.created_at is not None
    assert db.get_chat_settings(7).tz_offset_minutes == 180
    with db.connect() as conn:
        reminder_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)")}
        settings_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_settings)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(reminders)")}
    assert {"job_name", "repeat_rule", "is_archived", "done_at", "created_at"} <= reminder_columns
    assert {"dayplan_enabled", "dayplan_time"} <= settings_columns
    assert {"idx_reminders_chat_archived_time", "idx_reminders_active_lookup"} <= indexes


def test_db_backup_rejects_source_as_destination(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    try:
        db.backup_to(db.db_path)
    except ValueError as exc:
        assert "different files" in str(exc)
    else:
        raise AssertionError("backup_to must reject overwriting its SQLite source")
