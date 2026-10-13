from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from personal_crm.accompaniment import overdue, prepare, render_overview
from personal_crm.adapters import FakeTransport
from personal_crm.models import Attempt, Guidance, History, Job, Profile, Reminder, Task
from personal_crm.schema import Deadline
from personal_crm.service import CRMError
from personal_crm.worker import Worker
from test_core import OWNER, ingest
from test_queue import scheduled


def date_deadline(value="2026-10-13"):
    return Deadline(precision="date", value=value, original="synthetic calendar date", timezone="Europe/Berlin")


def test_plan_moves_count_without_changing_deadline(service, factory, clock):
    _, created = ingest(service)
    task = service.command(OWNER, created["task"]["id"], 1, "deadline", deadline=date_deadline("2026-11-01"))
    task = service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, 13))
    assert task["plan_postponements"] == 0
    for day in (14, 15):
        task = service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, day))
    task = service.command(OWNER, task["id"], task["version"], "reminder", at=clock() + timedelta(hours=1))
    task = service.command(OWNER, task["id"], task["version"], "reminder", at=clock() + timedelta(hours=2))
    assert task["plan_postponements"] == 2
    task = service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, 16))
    assert task["deadline"]["value"] == "2026-11-01" and task["plan_postponements"] == 3
    task = service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, 16))
    assert task["plan_postponements"] == 3
    with factory() as s:
        guides = s.scalars(select(Guidance).where(Guidance.kind == "obstacle")).all()
        assert len(guides) == 1 and guides[0].payload == {"postponements": 3}
        assert s.get(Task, task["id"]).state == "active"


def test_obstacle_prompt_once_not_daily_and_no_auto_state_change(service, factory, clock):
    task = ingest(service)[1]["task"]
    for day in (13, 14, 15, 16):
        task = service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, day))
    transport = FakeTransport()
    worker = Worker(factory, transport, clock)
    assert worker.tick() == "sent"
    assert "Что мешает?" in transport.sent[0][2]
    assert "выберите сами" in transport.sent[0][2]
    clock.now += timedelta(days=7)
    assert worker.tick() == "idle"
    with factory() as s:
        assert s.get(Task, task["id"]).state == "active"
        assert s.get(Task, task["id"]).planned_on == date(2026, 10, 16)
        assert s.scalar(select(func.count()).select_from(Guidance)) == 1


def test_plan_change_cancels_repeat_not_exact_deadline(service, factory, clock):
    task_id = scheduled(service, clock)
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick() == "sent"
    changed = service.command(OWNER, task_id, 2, "plan", planned_on=date(2026, 10, 14))
    assert changed["deadline"] is None
    with factory() as s:
        assert s.scalar(select(Job).where(Job.kind == "repeat")).status == "cancelled"
        assert s.scalar(select(Job).where(Job.kind == "exact")).status == "sent"
    clock.now += timedelta(hours=4)
    assert worker.tick() == "idle"


def test_defer_cancels_queue_returns_on_profile_date(service, factory, clock):
    task_id = scheduled(service, clock)
    task = service.command(OWNER, task_id, 2, "defer", return_on=date(2026, 10, 14))
    assert task["state"] == "deferred"
    assert not service.overview(OWNER)["main"]
    clock.now = datetime(2026, 10, 13, 22, 1, tzinfo=UTC)  # Berlin calendar day is October 14.
    prepare(factory, clock())
    with factory() as s:
        task = s.get(Task, task_id)
        assert task.state == "active" and task.return_on is None and task.version == 4
        assert s.scalar(select(Job)).status == "cancelled"
        assert s.scalar(select(History).where(History.reason == "scheduled_return")).actor == "system"
    prepare(factory, clock())
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(History).where(History.reason == "scheduled_return")) == 1


def test_explicit_resume_and_cancel_do_not_assume_completion(service, factory):
    task = ingest(service)[1]["task"]
    task = service.command(OWNER, task["id"], 1, "defer", return_on=date(2026, 10, 20))
    task = service.command(OWNER, task["id"], task["version"], "resume")
    assert task["state"] == "active" and task["return_on"] is None
    task = service.command(OWNER, task["id"], task["version"], "cancel")
    assert task["state"] == "cancelled"
    with pytest.raises(CRMError, match="task_inactive"):
        service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, 21))


def test_unknown_profile_timezone_blocks_calendar_not_exact(service, factory, clock):
    task = ingest(service)[1]["task"]
    with factory.begin() as s:
        s.get(Profile, OWNER).timezone = None
    with pytest.raises(CRMError, match="profile_timezone_required"):
        service.command(OWNER, task["id"], 1, "plan", planned_on=date(2026, 10, 14))
    assert service.overview(OWNER)["needs_timezone"] is True
    service.command(OWNER, task["id"], 1, "reminder", at=clock())
    assert Worker(factory, FakeTransport(), clock).tick() == "sent"


def test_overview_ranks_focus_preserves_all_deadlines_and_separate_dates(service, factory, clock):
    undated = []
    for i in range(5):
        undated.append(ingest(service, f"undated-{i}")[1]["task"])
    focused = service.command(OWNER, undated[-1]["id"], 1, "focus", focused=True)
    for day in (15, 16, 17, 18):
        task = ingest(service, f"dated-{day}")[1]["task"]
        service.command(OWNER, task["id"], 1, "deadline", deadline=date_deadline(f"2026-10-{day}"))
    ingest(service, "wait", text="synthetic wait")
    ingest(service, "mail", channel="mail")
    view = service.overview(OWNER)
    assert view["main"][0]["id"] == focused["id"] and len(view["main"]) == 3
    assert len(view["deadlines"]) == 4 and len(view["forgotten"]) == 2
    assert len(view["waiting"]) == len(view["proposals"]) == 1
    assert view["other_count"] == 7
    assert all(item["deadline"]["precision"] == "date" for item in view["deadlines"])


def test_note_is_not_a_digest_obligation(service, interpreter, clock, factory):
    interpreter.fixtures["synthetic note"] = dict(operation="create", title="Synthetic note", kind="note", obvious=True)
    ingest(service, text="synthetic note")
    assert render_overview(service.overview(OWNER)) is None
    clock.now += timedelta(hours=4)
    assert Worker(factory, FakeTransport(), clock).tick(digest=True) == "empty"


def test_successful_digest_rotates_forgotten_manual_overview_changes_nothing(service, factory, clock):
    tasks = [ingest(service, f"task-{i}")[1]["task"]["id"] for i in range(4)]
    first = service.overview(OWNER)
    assert service.overview(OWNER) == first
    with factory() as s:
        assert all(t.last_presented_at is None for t in s.scalars(select(Task)))
        assert s.scalar(select(func.count()).select_from(Attempt)) == 0
    clock.now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick(digest=True) == "sent"
    next_view = service.overview(OWNER)
    assert {t["id"] for t in first["forgotten"]}.isdisjoint({t["id"] for t in next_view["forgotten"]})
    assert {t["id"] for t in first["forgotten"] + next_view["forgotten"]} == set(tasks)


def test_date_deadline_not_overdue_until_next_local_date():
    deadline = date_deadline().model_dump()
    assert not overdue(deadline, datetime(2026, 10, 13, 20, tzinfo=UTC))
    assert overdue(deadline, datetime(2026, 10, 13, 22, 1, tzinfo=UTC))
    assert deadline["value"] == "2026-10-13"  # no invented 23:59 instant


def test_overdue_announcement_once_and_original_deadline_retained(service, factory, clock):
    task = ingest(service)[1]["task"]
    task = service.command(OWNER, task["id"], 1, "deadline", deadline=date_deadline("2026-10-12"))
    transport = FakeTransport()
    worker = Worker(factory, transport, clock)
    assert worker.tick() == "sent"
    assert "Срок прошёл" in transport.sent[0][2]
    task = service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, 20))
    clock.now += timedelta(days=1)
    assert worker.tick() == "idle"
    assert service.overview(OWNER)["deadlines"][0]["overdue"]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Guidance).where(Guidance.kind == "overdue")) == 1
        assert s.get(Task, task["id"]).state == "active"
    assert task["deadline"]["value"] == "2026-10-12" and task["original_deadline"] is None


def test_full_initiative_budget_reports_overdue_in_digest_once(service, factory, clock):
    task = ingest(service)[1]["task"]
    service.command(OWNER, task["id"], 1, "deadline", deadline=date_deadline("2026-10-12"))
    with factory.begin() as s:
        s.get(Profile, OWNER).initiative_limit = 0
    transport = FakeTransport()
    worker = Worker(factory, transport, clock)
    assert worker.tick() == "limited"
    clock.now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    # A due delayed initiative may be selected before digest; it cannot send.
    outcomes = [worker.tick(digest=True) for _ in range(3)]
    assert "sent" in outcomes and len(transport.sent) == 1
    assert "Срок прошёл" in transport.sent[0][2]
    with factory() as s:
        assert s.scalar(select(Guidance)).status == "sent"
        assert s.scalar(select(Job).where(Job.guidance_id.is_not(None))).status == "cancelled"
    clock.now += timedelta(days=1)
    worker.tick(digest=True)
    assert all("Срок прошёл" not in item[2] for item in transport.sent[1:])


def test_closed_task_before_overdue_send_suppresses_guidance(service, factory, clock):
    task = ingest(service)[1]["task"]
    service.command(OWNER, task["id"], 1, "deadline", deadline=date_deadline("2026-10-12"))
    prepare(factory, clock())
    worker = Worker(factory, FakeTransport(), clock)
    claimed = worker.claim()
    service.command(OWNER, task["id"], 2, "close")
    assert worker.deliver(*claimed) == "stale"
    assert not worker.transport.sent


def test_outage_consolidates_old_exact_reminders_and_keeps_tasks(service, factory, clock):
    for i in range(5):
        task = ingest(service, f"old-{i}")[1]["task"]
        service.command(OWNER, task["id"], 1, "reminder", at=clock())
    clock.now += timedelta(days=3)
    transport = FakeTransport()
    worker = Worker(factory, transport, clock)
    assert worker.tick() == "sent"
    assert len(transport.sent) == 1 and "пропущено напоминаний: 5" in transport.sent[0][2]
    assert worker.tick() == "idle"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task).where(Task.state == "active")) == 5
        assert s.scalar(select(func.count()).select_from(Job).where(Job.cancel_reason == "missed_after_outage")) == 5
        assert s.scalar(select(func.count()).select_from(Attempt)) == 1
        assert s.scalar(select(func.count()).select_from(Guidance)) == 1


def test_late_within_grace_is_labelled_and_unknown_attempt_not_a_definite_miss(service, factory, clock):
    scheduled(service, clock)
    clock.now += timedelta(minutes=30)
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick() == "sent"
    assert "Опоздавшее" in worker.transport.sent[0][2]
    _, task = ingest(service, "unknown")
    service.command(OWNER, task["task"]["id"], 1, "reminder", at=clock())
    claimed = worker.claim()
    with factory.begin() as s:
        s.add(Attempt(job_id=claimed[0], owner_id=OWNER, kind="exact", started_at=clock()))
    clock.now += timedelta(days=3)
    worker.tick()
    with factory() as s:
        assert s.get(Job, claimed[0]).status == "unknown"
        assert s.get(Job, claimed[0]).cancel_reason != "missed_after_outage"


def test_two_workers_consolidate_one_outage_report(service, factory, clock):
    for i in range(3):
        task = ingest(service, f"old-{i}")[1]["task"]
        service.command(OWNER, task["id"], 1, "reminder", at=clock())
    clock.now += timedelta(days=1)
    transports = [FakeTransport(), FakeTransport()]
    workers = [Worker(factory, transport, clock) for transport in transports]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda worker: worker.tick(), workers))
    assert sorted(outcomes) == ["idle", "sent"]
    assert sum(len(t.sent) for t in transports) == 1
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Guidance)) == 1


def test_four_week_simulation_keeps_rotation_and_daily_budget(service, factory, clock):
    ids = {ingest(service, f"simulation-{i}")[1]["task"]["id"] for i in range(8)}
    transport = FakeTransport()
    worker = Worker(factory, transport, clock)
    presented = set()
    clock.now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    for day in range(28):
        assert worker.tick(digest=True) == "sent"
        assert worker.tick(digest=True) == "idle"
        with factory() as s:
            attempt = s.scalar(select(Attempt).order_by(Attempt.started_at.desc()).limit(1))
            presented.update(attempt.payload["forgotten_ids"])
        clock.now += timedelta(days=1)
    assert presented == ids and len(transport.sent) == 28
    with factory() as s:
        assert all(t.state == "active" for t in s.scalars(select(Task)))
        assert all(t.plan_postponements == 0 for t in s.scalars(select(Task)))


def test_uncertain_overdue_send_not_reannounced_in_digest(service, factory, clock):
    task = ingest(service)[1]["task"]
    service.command(OWNER, task["id"], 1, "deadline", deadline=date_deadline("2026-10-12"))
    worker = Worker(factory, FakeTransport("unknown"), clock)
    assert worker.tick() == "unknown"
    with factory() as s:
        assert s.scalar(select(Guidance)).status == "unknown"
    clock.now += timedelta(days=1, hours=4)
    worker.transport = FakeTransport()
    assert worker.tick(digest=True) == "sent"
    assert "Срок прошёл" not in worker.transport.sent[0][2]
    assert service.overview(OWNER)["deadlines"][0]["overdue"]


def test_crash_during_digest_reservation_does_not_resend_one_time_question(service, factory, clock):
    task = ingest(service)[1]["task"]
    service.command(OWNER, task["id"], 1, "deadline", deadline=date_deadline("2026-10-12"))
    clock.now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    worker = Worker(factory, FakeTransport(), clock)
    worker.ensure_digest()
    # Synthetic interruption after durable intent, with no certainty about transport.
    with factory.begin() as s:
        guide = s.scalar(select(Guidance))
        job = s.scalar(select(Job).where(Job.kind == "digest"))
        job.status, job.lease_token, job.lease_until = "leased", "crashed", clock() - timedelta(seconds=1)
        s.add(Attempt(job_id=job.id, owner_id=OWNER, kind="digest", started_at=clock(),
                      payload={"guidance_ids": [guide.id]}))
        initiative = s.scalar(select(Job).where(Job.guidance_id == guide.id))
        initiative.run_at = clock() + timedelta(hours=1)
    assert worker.tick() == "idle"  # expired digest intent becomes unknown
    assert service.overview(OWNER)["guidance"] == []
    assert worker.tick() == "idle"  # reconcile guidance and cancel its standalone job
    clock.now += timedelta(days=1)
    assert worker.tick(digest=True) == "sent"
    assert "Срок прошёл" not in worker.transport.sent[0][2]
    with factory() as s:
        assert s.scalar(select(Guidance)).status == "unknown"


def test_model_plan_stays_proposal_and_stale_confirmation_rejected(service, interpreter, factory):
    task = ingest(service)[1]["task"]
    interpreter.fixtures["proposed plan"] = dict(operation="propose_update", target_id=task["id"], target_version=1,
                                                change="plan", planned_on="2026-10-20")
    _, result = ingest(service, "plan-proposal", channel="mail", text="proposed plan")
    with factory() as s:
        assert s.get(Task, task["id"]).planned_on is None
    service.command(OWNER, task["id"], 1, "focus", focused=True)
    with pytest.raises(CRMError, match="version_conflict"):
        service.confirm(OWNER, result["proposal_id"], 1)
    with factory() as s:
        assert s.get(Task, task["id"]).planned_on is None


def test_obstacle_and_plan_history_rollback_together(service, factory):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    task = ingest(service)[1]["task"]
    for day in (13, 14, 15):
        task = service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, day))
    with factory.begin() as s:
        s.execute(text("ALTER TABLE history ADD CONSTRAINT test_block_third_plan CHECK (task_version <> 5)"))
    try:
        with pytest.raises(IntegrityError):
            service.command(OWNER, task["id"], task["version"], "plan", planned_on=date(2026, 10, 16))
        with factory() as s:
            saved = s.get(Task, task["id"])
            assert saved.plan_postponements == 2 and saved.version == 4
            assert s.scalar(select(func.count()).select_from(Guidance)) == 0
    finally:
        with factory.begin() as s:
            s.execute(text("ALTER TABLE history DROP CONSTRAINT test_block_third_plan"))


def test_explicit_reschedule_makes_old_missed_report_inapplicable(service, factory, clock):
    task_id = scheduled(service, clock)
    clock.now += timedelta(days=3)
    prepare(factory, clock())
    assert service.overview(OWNER)["missed_reminders"]
    service.command(OWNER, task_id, 2, "reminder", at=clock() + timedelta(hours=1))
    assert not service.overview(OWNER)["missed_reminders"]
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick() == "stale"
    assert not worker.transport.sent
    with factory() as s:
        assert s.scalar(select(Guidance)).status == "resolved"
        assert s.scalar(select(Job).where(Job.cancel_reason == "missed_after_outage")) is not None


def test_closing_after_crashed_intent_keeps_unknown_outcome_instead_of_pending_forever(service, factory, clock):
    task_id = scheduled(service, clock)
    worker = Worker(factory, FakeTransport(), clock)
    job_id, token = worker.claim()
    with factory.begin() as s:
        s.add(Attempt(job_id=job_id, owner_id=OWNER, kind="exact", started_at=clock()))
    service.command(OWNER, task_id, 2, "close")
    assert worker.tick() == "idle"
    with factory() as s:
        assert s.get(Job, job_id).status == "cancelled"
        assert s.scalar(select(Attempt)).outcome == "unknown"
    assert not worker.transport.sent


def test_unannounced_restored_deadline_reuses_event_but_announced_one_never_repeats(service, factory, clock):
    task = ingest(service)[1]["task"]
    task = service.command(OWNER, task["id"], 1, "deadline", deadline=date_deadline("2026-10-12"))
    prepare(factory, clock())
    task = service.command(OWNER, task["id"], task["version"], "deadline", deadline=date_deadline("2026-11-01"))
    task = service.command(OWNER, task["id"], task["version"], "deadline", deadline=date_deadline("2026-10-12"))
    worker = Worker(factory, FakeTransport(), clock)
    assert worker.tick() == "sent"
    task = service.command(OWNER, task["id"], task["version"], "deadline", deadline=date_deadline("2026-11-01"))
    service.command(OWNER, task["id"], task["version"], "deadline", deadline=date_deadline("2026-10-12"))
    assert worker.tick() == "idle"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Guidance)) == 1
    assert len(worker.transport.sent) == 1


def test_delivery_crossing_profile_midnight_is_counted_on_actual_send_day(service, factory, clock):
    clock.now = datetime(2026, 10, 13, 21, 59, 50, tzinfo=UTC)  # Berlin midnight in ten seconds.
    scheduled(service, clock)
    class PausingWorker(Worker):
        renders = 0
        def _message(self, *args, **kwargs):
            result = super()._message(*args, **kwargs)
            self.renders += 1
            if self.renders == 1:
                clock.now += timedelta(seconds=20)
            return result
    assert PausingWorker(factory, FakeTransport(), clock).tick() == "sent"
    with factory() as s:
        attempt = s.scalar(select(Attempt))
        assert attempt.local_day == date(2026, 10, 14) and attempt.started_at == clock()
