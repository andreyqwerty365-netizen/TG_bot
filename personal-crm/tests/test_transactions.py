from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import subprocess
import sys

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from personal_crm.adapters import FakeTransport
from personal_crm.models import Attempt, History, Job, Proposal, SourceVersion, Task
from personal_crm.schema import Incoming
from personal_crm.service import CRMError
from personal_crm.worker import Worker
from test_core import OWNER, ingest
from test_queue import scheduled


def test_migration_down_up_and_no_drift(factory):
    env = {**os.environ, "CRM_DATABASE_URL": os.environ["CRM_TEST_DATABASE_URL"]}
    for args in [("downgrade", "base"), ("upgrade", "head"), ("upgrade", "head"), ("check",)]:
        subprocess.run([sys.executable, "-m", "alembic", *args], env=env, check=True)


def test_additive_upgrade_preserves_existing_core_records(factory):
    env = {**os.environ, "CRM_DATABASE_URL": os.environ["CRM_TEST_DATABASE_URL"]}
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0d16c4d28de5"], env=env, check=True)
    with factory.begin() as s:
        s.execute(text("INSERT INTO profiles(id, timezone, digest_hour, initiative_limit) VALUES ('synthetic-migration-owner', 'UTC', 12, 2)"))
        s.execute(text("INSERT INTO sources(id, owner_id, channel, account, external_id) VALUES ('migration-source','synthetic-migration-owner','owner','synthetic','one')"))
        s.execute(text("INSERT INTO source_versions(id, source_id, revision, text, received_at, status) VALUES ('migration-version','migration-source',1,'Synthetic migrated task',CURRENT_TIMESTAMP,'processed')"))
        s.execute(text("INSERT INTO tasks(id, owner_id, source_version_id, title, kind, state, version, created_at) VALUES ('migration-task','synthetic-migration-owner','migration-version','Synthetic migrated task','task','active',1,CURRENT_TIMESTAMP)"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    with factory() as s:
        task = s.get(Task, "migration-task")
        assert task.title == "Synthetic migrated task" and task.state == "active" and task.version == 1
        assert task.plan_postponements == 0 and task.focused is False
        assert s.get(SourceVersion, "migration-version").text == "Synthetic migrated task"


def test_task_history_queue_atomic_rollback(service, factory, clock):
    _, created = ingest(service)
    task_id = created["task"]["id"]
    # A real database rejection during history insertion must roll back task AND new job.
    with factory.begin() as s:
        s.execute(text("ALTER TABLE history ADD CONSTRAINT test_block_commands CHECK (reason <> 'explicit_command')"))
    try:
        with pytest.raises(IntegrityError):
            service.command(OWNER, task_id, 1, "reminder", at=clock())
        with factory() as s:
            assert s.get(Task, task_id).version == 1
            assert s.scalar(select(func.count()).select_from(Job)) == 0
            assert s.scalar(select(func.count()).select_from(History)) == 1
    finally:
        with factory.begin() as s:
            s.execute(text("ALTER TABLE history DROP CONSTRAINT test_block_commands"))


def test_interpretation_lease_recovered(service, interpreter, factory, clock):
    version_id = service.ingest(OWNER, "owner", Incoming(external_id="crashed-parse", account="synthetic", text="synthetic task"))
    with factory.begin() as s:
        version = s.get(SourceVersion, version_id)
        version.status, version.parse_token = "processing", "abandoned"
        version.parse_until = clock() + timedelta(seconds=30)
    assert service.process(OWNER, version_id)["status"] == "processing"
    assert interpreter.calls == 0
    clock.now += timedelta(seconds=31)
    assert service.process(OWNER, version_id)["status"] == "created"
    assert interpreter.calls == 1


def test_confirmation_other_owner_refused(service, factory):
    _, proposal = ingest(service, channel="mail")
    service.register("synthetic-outsider", "UTC")
    with pytest.raises(CRMError, match="not_found"):
        service.confirm("synthetic-outsider", proposal["proposal_id"], 1)
    with factory() as s:
        assert s.get(Proposal, proposal["proposal_id"]).status == "pending"


def test_parallel_initiatives_reserve_budget_under_owner_lock(service, factory, clock):
    scheduled(service, clock)
    _, second = ingest(service, "second")
    service.command(OWNER, second["task"]["id"], 1, "reminder", at=clock())
    with factory.begin() as s:
        for job in s.scalars(select(Job)):
            job.kind = "initiative"
    transports = [FakeTransport(), FakeTransport()]
    workers = [Worker(factory, transport, clock) for transport in transports]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda worker: worker.tick(), workers))
    assert sorted(outcomes) == ["limited", "sent"]
    assert sum(len(t.sent) for t in transports) == 1
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Attempt)) == 1


def test_deadline_ai_change_is_pending_until_confirmation(service, interpreter, factory):
    _, created = ingest(service)
    task_id = created["task"]["id"]
    interpreter.fixtures["propose deadline"] = dict(operation="propose_update", target_id=task_id,
        target_version=1, change="deadline", deadline=dict(precision="date", value="2026-11-01",
        timezone="Europe/Berlin", original="synthetic proposed date"))
    _, proposal = ingest(service, "suggestion", text="propose deadline")
    with factory() as s:
        assert s.get(Task, task_id).deadline is None
    updated = service.confirm(OWNER, proposal["proposal_id"], 1)["task"]
    assert updated["deadline"]["value"] == "2026-11-01"
    assert updated["original_deadline"] is None
