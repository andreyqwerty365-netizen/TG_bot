from datetime import UTC, date, datetime
from pathlib import Path

from bot.db import Database
from bot.services.routines import digest_tasks, due_one_time_tasks, find_routine_day, pending_tasks


def make_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "notes.db")
    db.init()
    db.ensure_routine_profile(1)
    return db


def test_shift_profile_supports_day_night_and_off(tmp_path: Path):
    db = make_db(tmp_path)

    db.set_shift_day(1, date(2026, 9, 1), "day")
    db.set_shift_day(1, date(2026, 9, 2), "night")
    db.set_shift_day(1, date(2026, 9, 3), "off")

    assert [item.shift_type for item in db.list_shift_days(1, date(2026, 9, 1), 3)] == ["day", "night", "off"]


def test_night_routine_day_continues_after_midnight(tmp_path: Path):
    db = make_db(tmp_path)
    db.set_shift_day(1, date(2026, 9, 1), "night")
    db.start_routine_day(1, date(2026, 9, 1), "night", datetime(2026, 9, 1, 18, 17, tzinfo=UTC))

    context = find_routine_day(db, 1, datetime(2026, 9, 2, 2, 0, tzinfo=UTC))

    assert context is not None
    assert context.routine_date == date(2026, 9, 1)
    assert context.shift_type == "night"
    assert context.wake_local == datetime(2026, 9, 1, 18, 17, tzinfo=UTC)


def test_routine_day_does_not_exist_until_started_manually(tmp_path: Path):
    db = make_db(tmp_path)
    db.set_shift_day(1, date(2026, 9, 2), "day")

    assert find_routine_day(db, 1, datetime(2026, 9, 2, 10, 0, tzinfo=UTC)) is None


def test_one_time_task_is_delivered_once_and_not_in_digest(tmp_path: Path):
    db = make_db(tmp_path)
    db.set_shift_day(1, date(2026, 9, 2), "day")
    db.start_routine_day(1, date(2026, 9, 2), "day", datetime(2026, 9, 2, 7, 0, tzinfo=UTC))
    task_id = db.add_routine_task(1, "Почистить зубы", "all", 0, False, 60)
    now = datetime(2026, 9, 2, 7, 5, tzinfo=UTC)

    assert [task.id for task in due_one_time_tasks(db, 1, now)] == [task_id]
    assert digest_tasks(db, 1, now) == []

    assert db.record_routine_delivery(1, f"task:2026-09-02:{task_id}") is True
    assert db.record_routine_delivery(1, f"task:2026-09-02:{task_id}") is False
    assert due_one_time_tasks(db, 1, now) == []


def test_manual_today_list_includes_all_current_tasks(tmp_path: Path):
    db = make_db(tmp_path)
    db.set_shift_day(1, date(2026, 9, 2), "day")
    db.start_routine_day(1, date(2026, 9, 2), "day", datetime(2026, 9, 2, 7, 0, tzinfo=UTC))
    once_id = db.add_routine_task(1, "Разовая", "all", 0, False, 60)
    digest_id = db.add_routine_task(1, "До выполнения", "all", 0, True, 600)

    assert [task.id for task in pending_tasks(db, 1, datetime(2026, 9, 2, 7, 5, tzinfo=UTC))] == [once_id, digest_id]


def test_digest_excludes_completed_and_expired_tasks(tmp_path: Path):
    db = make_db(tmp_path)
    db.set_shift_day(1, date(2026, 9, 2), "day")
    db.start_routine_day(1, date(2026, 9, 2), "day", datetime(2026, 9, 2, 7, 0, tzinfo=UTC))
    active_id = db.add_routine_task(1, "Выпить лекарство", "day", 0, True, 600)
    done_id = db.add_routine_task(1, "Позвонить", "all", 0, True, 600)
    db.add_routine_task(1, "Утреннее дело", "all", 0, True, 30)
    db.set_routine_task_status(1, done_id, date(2026, 9, 2), "done")

    tasks = digest_tasks(db, 1, datetime(2026, 9, 2, 10, 0, tzinfo=UTC))

    assert [task.id for task in tasks] == [active_id]


def test_routine_settings_are_configurable(tmp_path: Path):
    db = make_db(tmp_path)

    db.set_routine_enabled(1, True)
    db.set_routine_digest_interval(1, 4)

    settings = db.get_routine_settings(1)
    assert settings.enabled is True
    assert settings.digest_interval_hours == 4
