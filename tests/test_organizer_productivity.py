from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bot.db import Database
from bot.services.organizer import build_next_reminder_text, build_tomorrow_plan, cleanup_completed_reminders


def test_next_reminder_shows_soonest_active_item(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.set_timezone(1, 0)

    fixed_now = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("bot.services.organizer.utc_now", lambda: fixed_now)

    db.add_reminder(1, "Сегодня вечером", datetime(2026, 2, 1, 18, 0, tzinfo=UTC))
    db.add_reminder(1, "Завтра утром", datetime(2026, 2, 2, 9, 0, tzinfo=UTC))

    text = build_next_reminder_text(db, 1)

    assert "Ближайшее напоминание" in text
    assert "Сегодня вечером" in text
    assert "18" in text


def test_tomorrow_overview_lists_only_tomorrow_items(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.set_timezone(1, 0)

    fixed_now = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("bot.services.organizer.utc_now", lambda: fixed_now)

    db.add_reminder(1, "Сегодня вечером", datetime(2026, 2, 1, 18, 0, tzinfo=UTC))
    db.add_reminder(1, "Завтра утром", datetime(2026, 2, 2, 9, 0, tzinfo=UTC))

    text = build_tomorrow_plan(db, 1)

    assert "Завтра" in text
    assert "Завтра утром" in text
    assert "Сегодня вечером" not in text


def test_cleanup_completed_reminders_moves_only_finished_into_archive(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    done_id = db.add_reminder(1, "Выполнено", datetime(2026, 2, 1, 10, 0, tzinfo=UTC), done_at=datetime(2026, 2, 1, 11, 0, tzinfo=UTC))
    pending_id = db.add_reminder(1, "Ещё нет", datetime(2026, 2, 1, 12, 0, tzinfo=UTC))

    cleaned = cleanup_completed_reminders(db, 1)

    archived = db.list_reminders(1, archived=True, include_done=True, limit=10)
    active = db.list_reminders(1, archived=False, include_done=True, limit=10)

    assert cleaned == 1
    assert any(reminder.id == done_id for reminder in archived)
    assert all(reminder.id != pending_id for reminder in archived)
    assert any(reminder.id == pending_id for reminder in active)
