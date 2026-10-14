import hashlib
import importlib
import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from personal_crm.models import History, Job, Reminder, SourceVersion, Task

OWNER = "synthetic-owner"


@pytest.fixture
def importer():
    return importlib.import_module("personal_crm.legacy_import")


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "synthetic-copy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE notes(id INTEGER PRIMARY KEY,chat_id INTEGER,text TEXT,created_at TEXT,is_archived INTEGER);
        CREATE TABLE reminders(id INTEGER PRIMARY KEY,chat_id INTEGER,text TEXT,remind_at TEXT,
          repeat_rule TEXT,is_archived INTEGER,done_at TEXT,created_at TEXT,job_name TEXT);
        CREATE TABLE chat_settings(chat_id INTEGER PRIMARY KEY,tz_offset_minutes INTEGER,dayplan_enabled INTEGER,dayplan_time TEXT);
        CREATE TABLE routine_tasks(id INTEGER PRIMARY KEY,chat_id INTEGER,text TEXT);
        INSERT INTO notes VALUES (1,101,'Синтетическая заметка','2026-01-01T08:00:00Z',0);
        INSERT INTO notes VALUES (2,101,'Синтетический архив','2026-01-01T08:00:00',1);
        INSERT INTO notes VALUES (3,999,'Other synthetic owner','2026-01-01T08:00:00Z',0);
        INSERT INTO reminders VALUES(1,101,'Синтетический повтор','2026-10-15T09:00:00Z','daily',0,NULL,'2026-01-01T08:00:00Z','old-job');
        INSERT INTO reminders VALUES(2,101,'Синтетическое завершение','2026-10-01T09:00:00Z',NULL,1,'2026-10-01T09:30:00Z','2026-01-01T08:00:00Z',NULL);
        INSERT INTO reminders VALUES(3,101,'Синтетический пропуск','2026-01-02T09:00:00Z',NULL,0,NULL,'2026-01-01T08:00:00Z',NULL);
        INSERT INTO chat_settings VALUES(101,180,1,'08:00');
        INSERT INTO routine_tasks VALUES(1,101,'Synthetic exercise untouched');
        """)
    return path


def apply(importer, factory, legacy, clock):
    preview = importer.inspect_legacy(legacy, 101, "Europe/Berlin", now=clock.now)
    return importer.import_legacy(factory, legacy, OWNER, 101, "Europe/Berlin", "synthetic-v1",
                                  preview["snapshot_sha256"], now=clock.now)


def test_preview_is_readonly_and_reports_unconverted_repeats(importer, legacy, clock):
    before = legacy.read_bytes()
    result = importer.inspect_legacy(legacy, 101, "Europe/Berlin", now=clock.now)
    assert result["counts"] == {"notes": 2, "reminders": 3}
    assert result["review"] == {"repeats": 1, "past_active_reminders": 1, "all_reminders_disabled": 3}
    assert result["snapshot_sha256"] == hashlib.sha256(before).hexdigest()
    assert legacy.read_bytes() == before
    assert list(legacy.parent.iterdir()) == [legacy]


def test_import_preserves_fields_and_never_starts_old_senders(importer, legacy, service, factory, clock):
    before = legacy.read_bytes()
    result = apply(importer, factory, legacy, clock)
    assert result["created"] == 5
    assert result["skipped"] == 0
    with factory() as s:
        tasks = {t.title: t for t in s.scalars(select(Task))}
        assert len(tasks) == 5
        assert tasks["Синтетическая заметка"].kind == "note"
        assert tasks["Синтетический архив"].state == "cancelled"
        assert tasks["Синтетическое завершение"].state == "done"
        assert tasks["Синтетический повтор"].state == "active"
        assert all(t.deadline is None and t.planned_on is None and t.recurrence_id is None for t in tasks.values())
        reminders = list(s.scalars(select(Reminder)))
        assert len(reminders) == 3 and all(not r.active for r in reminders)
        assert any(r.at == datetime(2026, 10, 15, 9, tzinfo=UTC) for r in reminders)
        assert s.scalar(select(func.count()).select_from(Job)) == 0
        assert s.scalar(select(func.count()).select_from(History)) == 5
        versions = list(s.scalars(select(SourceVersion)))
        assert all(v.status == "processed" for v in versions)
        assert any(v.channel_metadata["legacy"]["repeat_rule"] == "daily" for v in versions)
    assert legacy.read_bytes() == before
    with sqlite3.connect(legacy) as conn:
        assert conn.execute("SELECT text FROM routine_tasks").fetchone()[0] == "Synthetic exercise untouched"


def test_import_idempotent_and_changed_record_rolls_back_whole_batch(importer, legacy, service, factory, clock):
    apply(importer, factory, legacy, clock)
    assert apply(importer, factory, legacy, clock)["skipped"] == 5
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE reminders SET text='Synthetic changed' WHERE id=1")
        conn.execute("INSERT INTO notes VALUES(4,101,'Synthetic new','2026-01-01T08:00:00Z',0)")
    with pytest.raises(importer.ImportError, match="legacy_record_conflict"):
        apply(importer, factory, legacy, clock)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 5


def test_import_rejects_stale_preview_invalid_date_and_wal_sidecar(importer, legacy, service, factory, clock):
    preview = importer.inspect_legacy(legacy, 101, "Europe/Berlin", now=clock.now)
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE reminders SET remind_at='invalid' WHERE id=1")
    with pytest.raises(importer.ImportError, match="legacy_snapshot_changed"):
        importer.import_legacy(factory, legacy, OWNER, 101, "Europe/Berlin", "synthetic-v1", preview["snapshot_sha256"], now=clock.now)
    with pytest.raises(importer.ImportError, match="legacy_date_invalid"):
        importer.inspect_legacy(legacy, 101, "Europe/Berlin", now=clock.now)
    legacy.with_name(legacy.name + "-wal").write_bytes(b"synthetic incomplete copy")
    with pytest.raises(importer.ImportError, match="legacy_copy_not_standalone"):
        importer.inspect_legacy(legacy, 101, "Europe/Berlin", now=clock.now)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 0


def test_import_requires_explicit_timezone_and_existing_matching_owner(importer, legacy, service, factory, clock):
    with pytest.raises(importer.ImportError, match="legacy_timezone_required"):
        importer.inspect_legacy(legacy, 101, "", now=clock.now)
    preview = importer.inspect_legacy(legacy, 101, "UTC", now=clock.now)
    with pytest.raises(importer.ImportError, match="legacy_timezone_conflict"):
        importer.import_legacy(factory, legacy, OWNER, 101, "UTC", "synthetic-v1", preview["snapshot_sha256"], now=clock.now)


def test_imported_schedule_evidence_is_available_in_web_card(importer, legacy, service, factory, clock):
    from fastapi.testclient import TestClient
    from personal_crm.api import create_app
    from personal_crm.config import Settings
    apply(importer, factory, legacy, clock)
    with factory() as s:
        identity = s.scalar(select(Task.id).where(Task.title == 'Синтетический повтор'))
    client = TestClient(create_app(Settings(factory.kw['bind'].url.render_as_string(hide_password=False), OWNER,
                                          'synthetic-import-secret', timezone='Europe/Berlin')))
    result = client.get('/workspace/tasks/' + identity, headers={'Authorization':'Bearer synthetic-import-secret'})
    assert result.status_code == 200
    assert result.json()['reminder_at'] is None
    assert result.json()['legacy_import'] == {'reminder_at':'2026-10-15T09:00:00Z','repeat_rule':'daily'}
