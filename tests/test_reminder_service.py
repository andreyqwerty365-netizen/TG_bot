from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bot.db import Database
from bot.services.reminder_actions import ReminderService


class FakeJob:
    def __init__(self) -> None:
        self.removed = False

    def schedule_removal(self) -> None:
        self.removed = True


class FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, list[FakeJob]] = {}

    def get_jobs_by_name(self, name: str):
        return self.jobs.get(name, [])


class FakeApp:
    def __init__(self) -> None:
        self.job_queue = FakeJobQueue()


def test_complete_reminder_cancels_jobs_and_marks_done(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    remind_at = datetime(2026, 1, 30, 12, 0, tzinfo=UTC)
    reminder_id = db.add_reminder(1, "Купить воду", remind_at)

    app = FakeApp()
    app.job_queue.jobs[f"reminder:{reminder_id}"] = [FakeJob()]
    app.job_queue.jobs[f"retry10:{reminder_id}"] = [FakeJob()]

    service = ReminderService(db)
    result = service.complete(app, 1, reminder_id)

    assert result.ok is True
    updated = db.get_reminder(1, reminder_id)
    assert updated is not None and updated.done_at is not None
    assert all(job.removed for jobs in app.job_queue.jobs.values() for job in jobs)


def test_stale_complete_is_safe(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    remind_at = datetime(2026, 1, 30, 12, 0, tzinfo=UTC)
    reminder_id = db.add_reminder(1, "Купить воду", remind_at)
    db.mark_reminder_done(1, reminder_id)

    service = ReminderService(db)
    result = service.complete(FakeApp(), 1, reminder_id)

    assert result.ok is False
    assert "закрыто" in result.message


def test_complete_overdue_repeat_advances_to_next_future_occurrence(tmp_path: Path, monkeypatch):
    fixed_now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("bot.services.reminder_actions.utc_now", lambda: fixed_now)
    db = Database(tmp_path / "notes.db")
    db.init()
    reminder_id = db.add_reminder(1, "Ежедневная задача", datetime(2026, 5, 27, 9, 0, tzinfo=UTC), "day")

    result = ReminderService(db).complete(FakeApp(), 1, reminder_id)

    assert result.ok is True
    assert result.reminder is not None
    assert result.reminder.remind_at == datetime(2026, 5, 31, 9, 0, tzinfo=UTC)


def test_postpone_overdue_reminder_uses_tomorrow_from_now(tmp_path: Path, monkeypatch):
    fixed_now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("bot.services.reminder_actions.utc_now", lambda: fixed_now)
    db = Database(tmp_path / "notes.db")
    db.init()
    reminder_id = db.add_reminder(1, "Просроченная задача", datetime(2026, 5, 27, 9, 0, tzinfo=UTC))

    result = ReminderService(db).postpone_to_tomorrow(FakeApp(), 1, reminder_id)

    assert result.ok is True
    assert result.reminder is not None
    assert result.reminder.remind_at == datetime(2026, 5, 31, 9, 0, tzinfo=UTC)
