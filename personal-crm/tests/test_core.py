from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from personal_crm.adapters import FixtureInterpreter, real_ai
from personal_crm.models import History, Job, Proposal, Reminder, Source, SourceVersion, Task
from personal_crm.schema import Deadline, Incoming, Interpretation
from personal_crm.service import CRMError, CRMService

OWNER = "synthetic-owner"


def ingest(service, external="event-1", channel="owner", text="synthetic task", account="synthetic-account", revision=1):
    version = service.ingest(OWNER, channel, Incoming(external_id=external, account=account, text=text, revision=revision))
    return version, service.process(OWNER, version)


def test_create_without_deadline_commits_history(service, factory):
    version, result = ingest(service)
    assert result["status"] == "created"
    assert result["task"]["deadline"] is None
    with factory() as s:
        assert s.get(SourceVersion, version).status == "processed"
        assert s.scalar(select(func.count()).select_from(History)) == 1
        assert s.scalar(select(func.count()).select_from(Job)) == 0


def test_technical_dedup_and_account_scope(service, factory, interpreter):
    _, first = ingest(service)
    _, duplicate = ingest(service)
    assert duplicate == first
    assert interpreter.calls == 1
    ingest(service, account="another-synthetic-account")
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 2


def test_identical_manual_forwards_are_distinct(service, factory):
    ingest(service, "forward-1", "forward")
    ingest(service, "forward-2", "forward")
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 2


def test_source_committed_before_failure_and_retry(service, factory, interpreter):
    class Failing:
        def interpret(self, version_id, text):
            with factory() as s:
                assert s.get(SourceVersion, version_id).text == text
            raise TimeoutError("private contents must not escape")
    service.interpreter = Failing()
    version, result = ingest(service)
    assert result == {"status": "error", "source_version_id": version, "code": "interpretation_failed"}
    with factory() as s:
        assert s.get(SourceVersion, version).status == "error"
        assert s.scalar(select(func.count()).select_from(Task)) == 0
    service.interpreter = interpreter
    assert service.process(OWNER, version)["status"] == "created"


def test_unprocessed_source_survives_new_service(service, factory, interpreter):
    version = service.ingest(OWNER, "owner", Incoming(external_id="stopped", account="synthetic", text="synthetic task"))
    restarted = CRMService(factory, interpreter)
    assert restarted.process(OWNER, version)["status"] == "created"


def test_mail_only_proposal_confirmation_and_rejection(service, factory):
    _, proposed = ingest(service, channel="mail")
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 0
    accepted = service.confirm(OWNER, proposed["proposal_id"], 1)
    assert accepted["task"]["state"] == "active"
    with pytest.raises(CRMError, match="proposal_conflict"):
        service.confirm(OWNER, proposed["proposal_id"], 1)
    _, rejected = ingest(service, external="mail-2", channel="mail")
    service.confirm(OWNER, rejected["proposal_id"], 1, False)
    _, repeated = ingest(service, external="mail-2", channel="mail")
    assert repeated["proposal_id"] == rejected["proposal_id"]
    with factory() as s:
        assert s.get(Proposal, repeated["proposal_id"]).status == "rejected"


def test_untrusted_update_only_proposes_and_stale_confirmation(service, factory, interpreter):
    _, created = ingest(service)
    task = created["task"]
    interpreter.fixtures["malicious mail"] = dict(operation="propose_update", target_id=task["id"],
        target_version=1, change="close", obvious=True)
    _, proposed = ingest(service, "mail-2", "mail", "malicious mail")
    with factory() as s:
        assert s.get(Task, task["id"]).state == "active"
    service.command(OWNER, task["id"], 1, "title", title="Explicit owner revision")
    with pytest.raises(CRMError, match="version_conflict"):
        service.confirm(OWNER, proposed["proposal_id"], 1)
    with factory() as s:
        assert s.get(Task, task["id"]).state == "active"
        assert s.get(Proposal, proposed["proposal_id"]).status == "stale"


def test_forbidden_model_operation_never_applied(service, factory, interpreter):
    interpreter.fixtures["malicious mail"] = dict(operation="delete_all", obvious=True)
    _, result = ingest(service, channel="mail", text="malicious mail")
    assert result["status"] == "error"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 0


def test_waiting_and_unknown_old_relative_date(service, factory):
    _, waiting = ingest(service, text="synthetic wait")
    assert waiting["task"]["kind"] == "waiting"
    version = service.ingest(OWNER, "forward", Incoming(external_id="old", account="synthetic", text="завтра",
        original_at=datetime(2020, 1, 1, tzinfo=UTC)))
    assert service.process(OWNER, version)["status"] == "clarification"
    assert ingest(service, "independent")[1]["status"] == "created"


def test_invalid_date_keeps_source(service, interpreter, factory):
    interpreter.fixtures["invalid date"] = dict(operation="create", title="Synthetic", obvious=True,
        deadline=dict(precision="date", value="2026-02-30", timezone="Europe/Berlin", original="invalid"))
    version, result = ingest(service, text="invalid date")
    assert result["status"] == "error"
    with factory() as s:
        assert s.get(SourceVersion, version).text == "invalid date"


def test_reminder_move_preserves_original_deadline(service, factory, interpreter, clock):
    original = dict(precision="date", value="2026-10-20", timezone="Europe/Berlin", original="20 октября")
    interpreter.fixtures["dated"] = dict(operation="create", title="Dated", obvious=True, deadline=original)
    _, created = ingest(service, text="dated")
    task = created["task"]
    assert task["deadline"] == original
    changed = service.command(OWNER, task["id"], 1, "reminder", at=clock() + timedelta(hours=1))
    moved = service.command(OWNER, task["id"], 2, "reminder", at=clock() + timedelta(hours=2))
    assert changed["deadline"] == moved["deadline"] == moved["original_deadline"] == original
    with factory() as s:
        assert len(s.scalars(select(Job).where(Job.status == "pending")).all()) == 1
        assert len(s.scalars(select(Job).where(Job.status == "cancelled")).all()) == 1


def test_model_schedule_requires_confirmation(service, interpreter, factory, clock):
    interpreter.fixtures["suggest schedule"] = dict(operation="create", title="Synthetic", obvious=True,
                                                   reminder_at=clock().isoformat())
    _, proposed = ingest(service, text="suggest schedule")
    assert proposed["status"] == "proposal"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Job)) == 0
    service.confirm(OWNER, proposed["proposal_id"], 1)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Job)) == 1


def test_edited_source_immutable_version_requires_confirmation(service, factory, interpreter):
    version, created = ingest(service)
    interpreter.fixtures["edited"] = dict(operation="create", title="Edited", obvious=True)
    edited_version, proposed = ingest(service, text="edited", revision=2)
    assert proposed["status"] == "proposal"
    assert edited_version != version
    with factory() as s:
        assert s.get(SourceVersion, version).text == "synthetic task"
        assert s.get(Task, created["task"]["id"]).title == "Synthetic task"
    with pytest.raises(CRMError, match="source_revision_conflict"):
        ingest(service, text="other", revision=2)


def test_object_owner_and_versions_checked(service, factory, interpreter):
    _, created = ingest(service)
    service.register("synthetic-outsider", "UTC")
    with pytest.raises(CRMError, match="not_found"):
        service.command("synthetic-outsider", created["task"]["id"], 1, "close")
    with pytest.raises(CRMError, match="version_conflict"):
        service.command(OWNER, created["task"]["id"], 99, "close")


def test_concurrent_source_retry_creates_once(service, factory):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ingest(service), range(2)))
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 1
        assert s.scalar(select(func.count()).select_from(Source)) == 1


@pytest.mark.parametrize("kwargs", [dict(), dict(enabled=True, budget=1, consent=True),
    dict(enabled=True, key="synthetic", consent=True), dict(enabled=True, key="synthetic", budget=1),
    dict(enabled=True, key="synthetic", budget=1, consent=True)])
def test_no_real_ai_calls(monkeypatch, kwargs):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("external connection"))
    with pytest.raises(RuntimeError):
        real_ai(**kwargs)
