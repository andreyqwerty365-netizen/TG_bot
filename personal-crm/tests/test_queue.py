from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from personal_crm.adapters import FakeTransport
from personal_crm.models import Attempt, History, Job, Profile, Reminder, Task
from personal_crm.policy import notification_allowed
from personal_crm.worker import Worker
from test_core import OWNER, ingest


def scheduled(service, clock):
    _, result = ingest(service)
    task = result["task"]
    service.command(OWNER, task["id"], 1, "reminder", at=clock())
    return task["id"]


def test_send_restart_repeat_once_and_close(service, factory, clock):
    task_id = scheduled(service, clock)
    transport = FakeTransport()
    worker = Worker(factory, transport, clock)
    assert worker.tick() == "sent"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Attempt)) == 1
        assert s.scalar(select(func.count()).select_from(Job).where(Job.kind == "repeat")) == 1
        assert s.scalar(select(Attempt)).provider_id.startswith("fake:")
    clock.now += timedelta(hours=4)
    restarted = Worker(factory, transport, clock)
    assert restarted.tick() == "sent"
    clock.now += timedelta(hours=4)
    assert restarted.tick() == "idle"
    assert len(transport.sent) == 2
    service.command(OWNER, task_id, 2, "close")
    with factory() as s:
        assert s.get(Task, task_id).state == "done"
        assert s.scalar(select(func.count()).select_from(History)) == 3


def test_close_before_initial_send_cancels(service, factory, clock):
    task_id = scheduled(service, clock)
    worker = Worker(factory, FakeTransport(), clock)
    claimed = worker.claim()
    service.command(OWNER, task_id, 2, "close")
    assert worker.deliver(*claimed) == "stale"
    assert not worker.transport.sent
    with factory() as s:
        assert s.scalar(select(Job)).status == "cancelled"


def test_close_before_repeat_cancels(service, factory, clock):
    task_id = scheduled(service, clock)
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick() == "sent"
    service.command(OWNER, task_id, 2, "close")
    clock.now += timedelta(hours=4)
    assert worker.tick() == "idle"
    assert len(worker.transport.sent) == 1


def test_lease_recovery_and_fencing_old_worker(service, factory, clock):
    scheduled(service, clock)
    worker = Worker(factory, FakeTransport(), clock)
    old = worker.claim()
    assert worker.claim() is None
    clock.now += timedelta(seconds=31)
    recovered = Worker(factory, worker.transport, clock).claim()
    assert old[0] == recovered[0] and old[1] != recovered[1]
    assert worker.deliver(*old) == "stale"
    assert worker.deliver(*recovered) == "sent"


def test_two_workers_only_one_claim_and_delivery(service, factory, clock):
    scheduled(service, clock)
    transport = FakeTransport()
    workers = [Worker(factory, transport, clock), Worker(factory, transport, clock)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda w: w.tick(), workers))
    assert sorted(results) == ["idle", "sent"]
    assert len(transport.sent) == 1


def test_postgres_skip_locked_claims_other_job(service, factory, clock):
    scheduled(service, clock)
    _, created = ingest(service, "another")
    service.command(OWNER, created["task"]["id"], 1, "reminder", at=clock())
    worker = Worker(factory, FakeTransport(), clock)
    with factory.begin() as s:
        locked = s.scalar(select(Job).order_by(Job.run_at, Job.id).with_for_update().limit(1))
        claimed = worker.claim()
        assert claimed[0] != locked.id


def test_delivery_uncertainty_stops_retries(service, factory, clock):
    scheduled(service, clock)
    worker = Worker(factory, FakeTransport("unknown"), clock)
    assert worker.tick() == "unknown"
    clock.now += timedelta(days=1)
    assert worker.tick() == "idle"
    with factory() as s:
        assert s.scalar(select(Attempt)).outcome == "unknown"
        assert s.scalar(select(Job)).status == "unknown"


def test_crash_with_pending_attempt_marked_unknown(service, factory, clock):
    scheduled(service, clock)
    worker = Worker(factory, FakeTransport(), clock)
    job_id, token = worker.claim()
    with factory.begin() as s:
        job = s.get(Job, job_id)
        job.attempts = 1
        s.add(Attempt(job_id=job.id, owner_id=OWNER, kind=job.kind, started_at=clock()))
    clock.now += timedelta(seconds=31)
    assert worker.tick() == "idle"
    with factory() as s:
        assert s.get(Job, job_id).status == "unknown"
        assert s.scalar(select(Attempt)).outcome == "unknown"
    assert not worker.transport.sent


def test_known_failure_has_bounded_retries(service, factory, clock):
    scheduled(service, clock)
    worker = Worker(factory, FakeTransport("error"), clock)
    assert worker.tick() == "pending"
    clock.now += timedelta(minutes=1)
    assert worker.tick() == "pending"
    clock.now += timedelta(minutes=2)
    assert worker.tick() == "failed"
    clock.now += timedelta(days=1)
    assert worker.tick() == "idle"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Attempt)) == 3


def test_exact_exempt_repeat_consumes_limit(service, factory, clock):
    scheduled(service, clock)
    with factory.begin() as s:
        s.add(Attempt(job_id=s.scalar(select(Job.id)), owner_id=OWNER, kind="initiative",
                      started_at=clock() - timedelta(hours=1), outcome="success"))
        s.add(Attempt(job_id=s.scalar(select(Job.id)), owner_id=OWNER, kind="initiative",
                      started_at=clock() - timedelta(hours=5), outcome="success"))
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick() == "sent"
    clock.now += timedelta(hours=4)
    assert worker.tick() == "limited"
    assert len(worker.transport.sent) == 1
    with factory.begin() as s:
        s.scalar(select(Profile)).initiative_limit = 0
    clock.now += timedelta(days=1)
    assert worker.tick() == "limited"


def test_digest_one_per_day_empty_and_stale(service, factory, clock):
    clock.now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick(digest=True) == "empty"
    ingest(service)
    assert worker.tick(digest=True) == "idle"
    clock.now += timedelta(days=1)
    assert worker.tick(digest=True) == "sent"
    assert worker.tick(digest=True) == "idle"
    clock.now += timedelta(days=1)
    worker.ensure_digest()
    clock.now += timedelta(days=1)
    assert worker.tick() == "stale_digest"


def test_policy_gap_crosses_midnight_and_dst():
    before = datetime(2026, 10, 24, 21, 30, tzinfo=UTC)
    after = before + timedelta(hours=3)
    assert not notification_allowed("initiative", after, "Europe/Berlin", [("initiative", before)])
    assert notification_allowed("initiative", before + timedelta(hours=4), "Europe/Berlin", [("initiative", before)])
    assert notification_allowed("exact", after, None, [])
    assert not notification_allowed("repeat", after, None, [])
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    assert not notification_allowed("initiative", now, "Europe/Berlin", [
        ("initiative", datetime(2026, 10, 25, 0, tzinfo=UTC)),
        ("repeat", datetime(2026, 10, 25, 4, tzinfo=UTC))])
