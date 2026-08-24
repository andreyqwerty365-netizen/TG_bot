from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bot.db import Database
from bot.services.import_export import build_export_payload, import_payload
from bot.services.organizer import build_next_reminder_text, build_overdue_reminders_text, build_today_plan, smart_capture
from bot.services.search_text import build_search_text


def test_smart_capture_creates_note_or_reminder(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    note_result = smart_capture(db, 1, "Просто заметка")
    reminder_result = smart_capture(db, 1, "10м созвон")

    assert note_result.kind == "note"
    assert reminder_result.kind == "reminder"
    assert reminder_result.reminder_id is not None


def test_build_search_text_finds_notes_and_reminders(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.add_note(1, "Купить молоко")
    db.add_reminder(1, "Купить кофе", datetime(2026, 2, 1, 9, 0, tzinfo=UTC))

    text = build_search_text(db, 1, "Купить")

    assert "Поиск" in text
    assert "Заметки" in text
    assert "Напоминания" in text


def test_import_export_preserves_timestamps(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    created_at = datetime(2026, 1, 20, 10, 0, tzinfo=UTC)
    remind_at = datetime(2026, 1, 21, 11, 0, tzinfo=UTC)
    done_at = datetime(2026, 1, 21, 11, 30, tzinfo=UTC)

    db.add_note(1, "Архивная заметка", created_at=created_at)
    reminder_id = db.add_reminder(1, "Важное", remind_at, "day", created_at=created_at, done_at=done_at)
    db.archive_reminder(1, reminder_id)

    payload = build_export_payload(db, 1)

    restored = Database(tmp_path / "restored.db")
    restored.init()
    result = import_payload(restored, 1, payload)

    imported_archived = restored.list_reminders(1, archived=True, include_done=True, limit=10)
    assert result.imported_archived_reminders == 1
    assert imported_archived[0].created_at == created_at
    assert imported_archived[0].done_at == done_at


def test_build_today_plan_shows_due_sections(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.set_timezone(1, 0)

    now = datetime.now(tz=UTC)
    db.add_reminder(1, "Просроченное", now.replace(hour=max(0, now.hour - 1), minute=0))
    db.add_reminder(1, "Сегодняшнее", now.replace(hour=min(23, now.hour + 1), minute=0))

    text = build_today_plan(db, 1)

    assert "Просрочено" in text
    assert "Сегодня" in text


def test_next_and_overdue_texts_are_compact_and_clear(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.set_timezone(1, 0)

    fixed_now = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("bot.services.organizer.utc_now", lambda: fixed_now)

    db.add_reminder(1, "Старое", datetime(2026, 2, 1, 10, 0, tzinfo=UTC))
    db.add_reminder(1, "Будущее", datetime(2026, 2, 1, 18, 0, tzinfo=UTC))

    next_text = build_next_reminder_text(db, 1)
    overdue_text = build_overdue_reminders_text(db, 1)

    assert "Ближайшее напоминание" in next_text
    assert "Будущее" not in next_text
    assert "Просроченные" in overdue_text
    assert "Старое" in overdue_text
