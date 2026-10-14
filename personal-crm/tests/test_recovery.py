"""Real PostgreSQL dump/restore, with synthetic contents and isolated targets only."""
import base64
import importlib
import os
import shutil
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import make_url, select, text

from personal_crm.adapters import FakeTransport
from personal_crm.db import sessions
from personal_crm.models import Job, Profile, Reminder, SourceVersion, Task
from personal_crm.schema import Incoming
from personal_crm.service import CRMError
from personal_crm.worker import Worker


KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()  # Synthetic key, never use outside tests.
OTHER_KEY = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode()
OWNER = "synthetic-owner"


@pytest.fixture
def recovery():
    return importlib.import_module("personal_crm.recovery")


@pytest.fixture
def pg_bin():
    configured = os.getenv("CRM_TEST_PG_BIN")
    detected = shutil.which("pg_dump")
    if not configured and not detected:
        pytest.skip("Set CRM_TEST_PG_BIN to PostgreSQL client tools for real dump/restore tests")
    return Path(configured) if configured else Path(detected).parent


@pytest.fixture
def target(factory):
    source = make_url(os.environ["CRM_TEST_DATABASE_URL"])
    name = "personal_crm_test_restore_" + uuid4().hex[:12]
    args = dict(host=source.host, port=source.port, user=source.username,
                password=source.password, dbname="postgres")
    with psycopg.connect(**args, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    url = source.set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with psycopg.connect(**args, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def seed(service, factory, clock):
    version = service.ingest(OWNER, "owner", Incoming(account="synthetic", external_id="backup-task", text="synthetic task"))
    task_id = service.process(OWNER, version)["task"]["id"]
    service.command(OWNER, task_id, 1, "reminder", at=clock.now + timedelta(hours=1))
    with factory.begin() as s:
        s.add(Job(owner_id=OWNER, kind="digest", dedupe_key="synthetic-unknown", run_at=clock.now, status="unknown"))
    return task_id


def archive(recovery, factory, tmp_path, pg_bin, clock):
    ledger = tmp_path / "erasures.crme"
    recovery.initialize_ledger(ledger, KEY)
    report = recovery.create_backup(os.environ["CRM_TEST_DATABASE_URL"], tmp_path, KEY, pg_bin, ledger, now=clock.now)
    return tmp_path / report["file"], ledger


def test_encryption_authenticates_every_byte_and_randomizes_nonce(recovery):
    first = recovery.seal(b"synthetic private data", KEY, "backup")
    assert b"synthetic private data" not in first
    assert first != recovery.seal(b"synthetic private data", KEY, "backup")
    assert recovery.unseal(first, KEY, "backup") == b"synthetic private data"
    for value, key, purpose in [(first, OTHER_KEY, "backup"), (first[:-1], KEY, "backup"),
                                (first, KEY, "ledger"), (b"broken", KEY, "backup")]:
        with pytest.raises(recovery.RecoveryError, match="archive_authentication_failed"):
            recovery.unseal(value, key, purpose)
    with pytest.raises(recovery.RecoveryError, match="key_invalid"):
        recovery.seal(b"x", "short", "backup")


def test_postgresql_restore_preserves_evidence_and_holds_all_delivery(recovery, service, factory, clock, tmp_path, pg_bin, target):
    task_id = seed(service, factory, clock)
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    report = recovery.inspect_backup(path, KEY)
    assert report["counts"]["tasks"] == 1
    assert report["schema_revision"]
    assert b"Synthetic task" not in path.read_bytes()
    result = recovery.restore_backup(path, KEY, target, pg_bin, ledger)
    assert result["status"] == "restored_on_hold"
    restored = sessions(target)
    with restored() as s:
        assert s.get(Task, task_id).title == "Synthetic task"
        assert s.get(Task, task_id).deadline is None
        assert s.get(Profile, OWNER).recovery_hold
        assert s.get(Profile, OWNER).ai_paused
        assert not s.scalar(select(Reminder.active))
        assert set(s.scalars(select(Job.status))) == {"cancelled", "unknown"}
        assert s.scalar(select(SourceVersion.text)) == "synthetic task"
    transport = FakeTransport()
    assert Worker(restored, transport, clock).claim() is None
    recovery.release_hold(target, OWNER, ledger, KEY)
    with restored() as s:
        assert not s.get(Profile, OWNER).recovery_hold
        assert s.get(Profile, OWNER).ai_paused
        assert set(s.scalars(select(Job.status))) == {"cancelled", "unknown"}
    restored.kw["bind"].dispose()


def test_restore_rejects_nonempty_target_without_changing_it(recovery, service, factory, clock, tmp_path, pg_bin, target):
    seed(service, factory, clock)
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    f = sessions(target)
    with f.begin() as s:
        s.execute(text("CREATE TABLE synthetic_sentinel (id integer PRIMARY KEY)"))
        s.execute(text("INSERT INTO synthetic_sentinel VALUES (42)"))
    with pytest.raises(recovery.RecoveryError, match="restore_target_not_empty"):
        recovery.restore_backup(path, KEY, target, pg_bin, ledger)
    with f() as s:
        assert s.scalar(text("SELECT id FROM synthetic_sentinel")) == 42
    f.kw["bind"].dispose()


def test_restore_requires_isolated_name_and_authenticated_current_ledger(recovery, service, factory, clock, tmp_path, pg_bin, target):
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    unsafe = make_url(target).set(database="synthetic_production").render_as_string(hide_password=False)
    with pytest.raises(recovery.RecoveryError, match="restore_target_name_forbidden"):
        recovery.restore_backup(path, KEY, unsafe, pg_bin, ledger)
    ledger.write_bytes(b"broken")
    with pytest.raises(recovery.RecoveryError, match="archive_authentication_failed"):
        recovery.restore_backup(path, KEY, target, pg_bin, ledger)
    with pytest.raises(recovery.RecoveryError, match="ledger_unavailable"):
        recovery.restore_backup(path, KEY, target, pg_bin, tmp_path / "absent")


def test_registered_erasure_is_reapplied_to_older_backup(recovery, service, factory, clock, tmp_path, pg_bin, target):
    seed(service, factory, clock)
    service.register("synthetic-other", "UTC")
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    recovery.erase_owner(os.environ["CRM_TEST_DATABASE_URL"], OWNER, ledger, KEY)
    recovery.erase_owner(os.environ["CRM_TEST_DATABASE_URL"], OWNER, ledger, KEY)  # Crash/retry safe.
    with factory() as s:
        assert s.get(Profile, OWNER) is None
        assert s.scalar(select(Task.id)) is None
    result = recovery.restore_backup(path, KEY, target, pg_bin, ledger)
    assert result["erased_profiles"] == 1
    restored = sessions(target)
    with restored() as s:
        assert s.get(Profile, OWNER) is None
        assert s.scalar(select(SourceVersion.id)) is None
        assert s.get(Profile, "synthetic-other").recovery_hold
    restored.kw["bind"].dispose()


def test_hold_blocks_commands_mail_and_even_fresh_jobs(recovery, service, factory, clock):
    with factory.begin() as s:
        s.get(Profile, OWNER).recovery_hold = True
        s.add(Job(owner_id=OWNER, kind="digest", dedupe_key="held", run_at=clock.now))
    with pytest.raises(CRMError, match="recovery_hold"):
        service.ingest(OWNER, "owner", Incoming(account="synthetic", external_id="held", text="synthetic task"))
    assert Worker(factory, FakeTransport(), clock).claim() is None
    from personal_crm.accompaniment import prepare
    prepare(factory, clock.now, digest=True)
    with factory() as s:
        assert len(list(s.scalars(select(Job)))) == 1


def test_retention_keeps_current_copy_and_ignores_foreign_files(recovery, service, factory, clock, tmp_path, pg_bin):
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    foreign = tmp_path / "foreign.crmb"
    foreign.write_bytes(b"foreign")
    corrupt = tmp_path / "crm-20200101T000000Z-aaaaaaaaaaaa.crmb"
    corrupt.write_bytes(b"corrupt")
    new = recovery.create_backup(os.environ["CRM_TEST_DATABASE_URL"], tmp_path, KEY, pg_bin, ledger,
                                 now=clock.now + timedelta(days=31))
    assert not path.exists()
    assert (tmp_path / new["file"]).exists()
    assert foreign.read_bytes() == b"foreign"
    assert corrupt.read_bytes() == b"corrupt"
    assert ledger.exists()


def test_wrong_key_restore_leaves_empty_target(recovery, service, factory, clock, tmp_path, pg_bin, target):
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    with pytest.raises(recovery.RecoveryError, match="archive_authentication_failed"):
        recovery.restore_backup(path, OTHER_KEY, target, pg_bin, ledger)
    f = sessions(target)
    with f() as s:
        assert s.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")) == 0
    f.kw["bind"].dispose()


def test_count_mismatch_rolls_back_schema_and_quarantine(recovery, service, factory, clock, tmp_path, pg_bin, target):
    import json
    import struct
    seed(service, factory, clock)
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    manifest, dump = recovery._unpack(path, KEY)
    manifest["counts"]["tasks"] += 1
    encoded = json.dumps(manifest).encode()
    path.write_bytes(recovery.seal(struct.pack('!I', len(encoded)) + encoded + dump, KEY, "backup"))
    with pytest.raises(recovery.RecoveryError, match="postgresql_tool_failed"):
        recovery.restore_backup(path, KEY, target, pg_bin, ledger)
    f = sessions(target)
    with f() as s:
        assert s.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")) == 0
    f.kw["bind"].dispose()


def test_daily_backup_cycle_is_opt_in_and_checks_archive_authentication(recovery, service, factory, clock, tmp_path, pg_bin):
    config = recovery.BackupConfig(database_url=os.environ["CRM_TEST_DATABASE_URL"], directory=tmp_path,
                                  pg_bin=pg_bin, key=KEY, ledger=tmp_path / 'erasures.crme')
    assert KEY not in repr(config)
    assert recovery.backup_cycle(config, now=clock.now)["status"] == "disabled"
    assert list(tmp_path.iterdir()) == []
    from dataclasses import replace
    enabled = replace(config, enabled=True, external_target_confirmed=True)
    recovery.initialize_ledger(config.ledger, KEY)
    assert recovery.backup_cycle(enabled, now=clock.now)["status"] == "backed_up"
    assert recovery.backup_cycle(enabled, now=clock.now + timedelta(hours=23))["status"] == "not_due"
    assert recovery.backup_cycle(enabled, now=clock.now + timedelta(hours=24))["status"] == "backed_up"


def test_hold_is_visible_in_authenticated_api_and_export_is_owner_scoped(recovery, service, factory, clock):
    from fastapi.testclient import TestClient
    from personal_crm.api import create_app
    from personal_crm.config import Settings
    seed(service, factory, clock)
    service.register("synthetic-other", "UTC")
    version = service.ingest("synthetic-other", "owner", Incoming(account="synthetic", external_id="other", text="synthetic task"))
    service.process("synthetic-other", version)
    url = os.environ["CRM_TEST_DATABASE_URL"]
    app = TestClient(create_app(Settings(url, OWNER, "synthetic-export-secret", timezone="Europe/Berlin")))
    assert app.get('/workspace/export').status_code == 401
    result = app.get('/workspace/export', headers={'Authorization': 'Bearer synthetic-export-secret'})
    assert result.status_code == 200
    data = result.json()
    assert len(data['records']['tasks']) == 1
    assert len(data['records']['source_versions']) == 1
    assert "synthetic-other" not in result.text
    assert result.headers['Cache-Control'] == 'no-store'
    assert 'attachment' in result.headers['Content-Disposition']
    with factory.begin() as s:
        s.get(Profile, OWNER).recovery_hold = True
    result = app.get('/workspace/settings', headers={'Authorization': 'Bearer synthetic-export-secret'})
    assert result.status_code == 503 and result.json()['detail'] == 'recovery_hold'


def test_other_database_archive_cannot_suppress_daily_backup(recovery, service, factory, clock, tmp_path, pg_bin):
    import json
    import struct
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    manifest, dump = recovery._unpack(path, KEY)
    manifest['database_scope'] = '0' * 64
    encoded = json.dumps(manifest).encode()
    path.write_bytes(recovery.seal(struct.pack('!I', len(encoded)) + encoded + dump, KEY, 'backup'))
    config = recovery.BackupConfig(database_url=os.environ['CRM_TEST_DATABASE_URL'], directory=tmp_path,
                                  pg_bin=pg_bin, key=KEY, ledger=ledger, enabled=True, external_target_confirmed=True)
    assert recovery.backup_cycle(config, now=clock.now)['status'] == 'backed_up'
    assert path.exists()


def test_erasure_ledger_lock_prevents_lost_updates(recovery, service, factory, tmp_path):
    ledger = tmp_path / 'erasures.crme'
    recovery.initialize_ledger(ledger, KEY)
    with recovery.ledger_lock(ledger):
        with pytest.raises(recovery.RecoveryError, match='ledger_busy'):
            recovery.erase_owner(os.environ['CRM_TEST_DATABASE_URL'], OWNER, ledger, KEY)
        with factory() as s:
            assert s.get(Profile, OWNER) is not None
    recovery.erase_owner(os.environ['CRM_TEST_DATABASE_URL'], OWNER, ledger, KEY)
    assert recovery.owner_hash(OWNER) in recovery.read_ledger(ledger, KEY)['erased']


def test_dump_counts_and_records_share_snapshot_during_concurrent_writes(recovery, service, factory, clock, tmp_path, pg_bin, target, monkeypatch):
    task_id = seed(service, factory, clock)
    original = recovery._run
    def concurrent_write(pg_bin, name, args, url=None, data=None):
        if name == 'pg_dump':
            with factory.begin() as s:
                s.get(Task, task_id).title = 'Synthetic concurrent update'
            version = service.ingest(OWNER, 'owner', Incoming(account='synthetic',external_id='during-backup',text='synthetic task'))
            service.process(OWNER, version)
        return original(pg_bin, name, args, url, data)
    monkeypatch.setattr(recovery, '_run', concurrent_write)
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    assert recovery.inspect_backup(path, KEY)['counts']['tasks'] == 1
    recovery.restore_backup(path, KEY, target, pg_bin, ledger)
    restored = sessions(target)
    with restored() as s:
        assert s.get(Task, task_id).title == 'Synthetic task'
        assert len(list(s.scalars(select(Task)))) == 1
    with factory() as s:
        assert s.get(Task, task_id).title == 'Synthetic concurrent update'
        assert len(list(s.scalars(select(Task)))) == 2
    restored.kw['bind'].dispose()


def test_restore_never_replays_paid_requests_inflight_sources_or_mail(recovery, service, factory, clock, tmp_path, pg_bin, target):
    from personal_crm.models import AIReservation, Attempt, MailAccount, Recurrence
    task_id = seed(service, factory, clock)
    version_id = service.ingest(OWNER, 'owner', Incoming(account='synthetic',external_id='unparsed',text='synthetic task'))
    with factory.begin() as s:
        version = s.get(SourceVersion, version_id)
        version.status, version.parse_token, version.parse_until = 'processing', 'synthetic-parse', clock.now + timedelta(minutes=1)
        s.add(AIReservation(owner_id=OWNER, source_version_id=version_id, period=clock.now.date().replace(day=1),
                            model='synthetic-model', amount_micro_usd=100, status='reserved'))
        job = s.scalar(select(Job).where(Job.kind == 'exact'))
        job.status, job.lease_token, job.lease_until = 'leased', 'synthetic-lease', clock.now + timedelta(minutes=1)
        s.add(Attempt(owner_id=OWNER, job_id=job.id, kind='exact', outcome='pending', started_at=clock.now))
        s.add(MailAccount(owner_id=OWNER, provider='synthetic', account_key='synthetic', enabled=True))
        s.add(Recurrence(owner_id=OWNER, frequency='daily', interval=1, anchor_on=clock.now.date(),
                         timezone='Europe/Berlin', template={}, status='active'))
    path, ledger = archive(recovery, factory, tmp_path, pg_bin, clock)
    recovery.restore_backup(path, KEY, target, pg_bin, ledger)
    restored = sessions(target)
    with restored() as s:
        assert s.scalar(select(AIReservation.status)) == 'unknown'
        assert s.scalar(select(Attempt.outcome)) == 'unknown'
        version = s.get(SourceVersion, version_id)
        assert version.status == 'processed' and version.parse_token is None
        assert version.result['status'] == 'restore_review_required'
        assert not s.get(MailAccount, OWNER).enabled
        assert s.scalar(select(Recurrence.status)) == 'stopped'
        assert s.get(Task, task_id).state == 'active'
    restored.kw['bind'].dispose()


def test_erasure_binds_owner_identity_without_sql_or_line_interpretation(recovery, service, factory, tmp_path):
    unusual_owner = "synthetic-':parameter\nowner"
    service.register(unusual_owner, 'UTC')
    ledger = tmp_path / 'erasures.crme'
    recovery.initialize_ledger(ledger, KEY)
    recovery.erase_owner(os.environ['CRM_TEST_DATABASE_URL'], unusual_owner, ledger, KEY)
    with factory() as s:
        assert s.get(Profile, unusual_owner) is None
        assert s.get(Profile, OWNER) is not None
