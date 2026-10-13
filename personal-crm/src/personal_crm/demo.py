"""Repeatable synthetic scenario; requires a separate development PostgreSQL DB."""
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from .adapters import FixtureInterpreter, FakeTransport
from .db import sessions
from .models import Attempt, History, Job, SourceVersion, Task
from .schema import Incoming
from .service import CRMService
from .worker import Worker


def readback(url, owner_id, task_id):
    factory = sessions(url)
    with factory() as s:
        task = s.get(Task, task_id)
        assert task.owner_id == owner_id and task.state == "active"
        assert s.get(SourceVersion, task.source_version_id).status == "processed"
        history_count = s.scalar(select(func.count()).select_from(History).where(History.task_id == task_id))
        assert history_count == 2
    print("new process: source, task and two history records persisted")


def main():
    url = os.environ["CRM_DATABASE_URL"]
    if len(sys.argv) > 1 and sys.argv[1] == "--readback":
        readback(url, sys.argv[2], sys.argv[3])
        return
    factory = sessions(url)
    owner = f"demo-{uuid4().hex}"
    interpreter = FixtureInterpreter.from_file("fixtures/demo.json")
    now = [datetime.now(UTC)]
    clock = lambda: now[0]
    service = CRMService(factory, interpreter, clock)
    # Explicit synthetic profile, never a claimed timezone of the actual owner.
    service.register(owner, "Europe/Berlin")
    incoming = Incoming(external_id="owner-event", account="synthetic-demo", text="Подготовить синтетический отчёт")
    version_id = service.ingest(owner, "owner", incoming)
    created = service.process(owner, version_id)
    assert created["status"] == "created"
    task_id = created["task"]["id"]
    service.command(owner, task_id, 1, "reminder", at=clock())
    duplicate = service.ingest(owner, "owner", incoming)
    assert duplicate == version_id and service.process(owner, duplicate) == created
    assert interpreter.calls == 1
    subprocess.run([sys.executable, "-m", "personal_crm.demo", "--readback", owner, task_id], check=True)
    # Real separate worker process, fake transport; attempt is persisted in PostgreSQL.
    subprocess.run([sys.executable, "-m", "personal_crm.worker", "--once", "--no-digest", "--owner", owner], check=True)
    with factory() as s:
        attempt = s.scalar(select(Attempt).where(Attempt.owner_id == owner))
        assert attempt.outcome == "success" and attempt.provider_id.startswith("fake:")
        sent_at = attempt.started_at
    service.command(owner, task_id, 2, "close")
    now[0] = sent_at + timedelta(hours=4)
    transport = FakeTransport()
    worker = Worker(factory, transport, clock, owner_id=owner)
    assert worker.tick() == "idle"
    assert not transport.sent
    with factory() as s:
        assert s.scalar(select(Job).where(Job.owner_id == owner, Job.kind == "repeat")).status == "cancelled"
    mail_id = service.ingest(owner, "mail", Incoming(external_id="mail-event", account="synthetic-mail",
        text="Пожалуйста, проверьте учебный документ"))
    proposal = service.process(owner, mail_id)
    assert proposal["status"] == "proposal"
    confirmed = service.confirm(owner, proposal["proposal_id"], 1)
    with factory() as s:
        assert s.get(Task, task_id).state == "done"
        attempts = s.scalar(select(func.count()).select_from(Attempt).where(Attempt.owner_id == owner))
        assert attempts == 1
    print(json.dumps({"source_persisted": True, "duplicate_applied_once": True,
        "fake_delivery_attempts": attempts, "closed_repeat_cancelled": True,
        "mail_proposal_confirmed": confirmed["status"] == "accepted", "real_external_calls": 0}))


if __name__ == "__main__":
    main()
