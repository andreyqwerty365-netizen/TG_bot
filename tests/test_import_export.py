from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import bot.services.import_export as import_export
from bot.db import Database
from bot.models import Note
from bot.services.import_export import build_export_payload, import_payload


def test_export_import_with_dedup(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    note_id = db.add_note(1, "Купить воду")
    rem_id = db.add_reminder(1, "Созвон", datetime(2026, 2, 1, 9, 0, tzinfo=UTC), "week")
    db.archive_note(1, note_id)
    db.mark_reminder_done(1, rem_id)

    payload = build_export_payload(db, 1)
    assert payload["version"] == 5
    assert "chat_id" not in payload
    result = import_payload(db, 1, payload)
    assert result.skipped_duplicates >= 2

    payload["notes"]["active"].append({"text": "Новая заметка"})
    payload["reminders"]["active"].append(
        {
            "text": "Новый созвон",
            "remind_at": "2026-03-01T10:00:00Z",
            "repeat_rule": "day",
            "done_at": None,
        }
    )

    result2 = import_payload(db, 1, payload)
    assert result2.imported_notes == 1
    assert result2.imported_reminders == 1
    assert len(result2.scheduled_reminder_ids) == 1


def test_import_rejects_invalid_payload_before_database_changes(tmp_path: Path):
    db = Database(tmp_path / "notes.db", default_tz_offset_minutes=180)
    db.init()

    payload = {
        "tz_offset_minutes": 0,
        "notes": {"active": [{"text": "Не должна сохраниться"}]},
        "reminders": {
            "active": [
                {
                    "text": "Некорректный повтор",
                    "remind_at": "2026-03-01T10:00:00Z",
                    "repeat_rule": "hour",
                }
            ]
        },
    }

    with pytest.raises(ValueError, match="repeat_rule"):
        import_payload(db, 1, payload)

    assert db.count_notes(1) == 0
    assert db.count_reminders(1) == 0
    assert db.get_chat_settings(1).tz_offset_minutes == 180


def test_import_preserves_settings_omitted_by_legacy_payload(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.set_timezone(1, 180)
    db.set_dayplan(1, True, "08:30")

    import_payload(db, 1, {"notes": {"active": [{"text": "Старая копия"}]}})

    settings = db.get_chat_settings(1)
    assert settings.tz_offset_minutes == 180
    assert settings.dayplan_enabled is True
    assert settings.dayplan_time == "08:30"


def test_export_rejects_record_count_above_supported_limit():
    note = Note(1, 1, "Заметка", datetime(2026, 1, 1, tzinfo=UTC), False)
    db = SimpleNamespace(
        get_chat_settings=lambda chat_id: SimpleNamespace(tz_offset_minutes=0, dayplan_enabled=False, dayplan_time=None),
        list_notes=lambda chat_id, archived, limit: [note] * 10_001 if not archived else [],
        list_reminders=lambda chat_id, archived, include_done, limit: [],
    )

    with pytest.raises(ValueError, match="10000"):
        build_export_payload(db, 1)


def test_import_rolls_back_all_changes_when_write_fails(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.set_timezone(1, 180)
    db.set_dayplan(1, True, "08:30")
    payload = {
        "tz_offset_minutes": 0,
        "dayplan_enabled": False,
        "dayplan_time": None,
        "notes": {"active": [{"text": "Не должна сохраниться"}]},
        "reminders": {"active": [{"text": "Сбой", "remind_at": "2026-03-01T10:00:00Z"}]},
    }

    monkeypatch.setattr(import_export, "_insert_reminder", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")))

    with pytest.raises(RuntimeError, match="disk full"):
        import_payload(db, 1, payload)

    assert db.count_notes(1) == 0
    assert db.count_reminders(1) == 0
    settings = db.get_chat_settings(1)
    assert settings.tz_offset_minutes == 180
    assert settings.dayplan_enabled is True
    assert settings.dayplan_time == "08:30"


def test_import_rejects_malformed_record_instead_of_skipping_it(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    with pytest.raises(ValueError, match="Текст заметки"):
        import_payload(db, 1, {"notes": {"active": [{"text": ""}]}})

    assert db.count_notes(1) == 0
