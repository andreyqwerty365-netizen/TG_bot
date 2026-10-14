"""Real PostgreSQL and synthetic channels; no external services or owner data."""
from datetime import UTC, datetime, timedelta
import json

import httpx2
import pytest
from sqlalchemy import func, select

from personal_crm.models import Dialogue, History, Job, Reminder, Source, SourceVersion, Task, uid
from personal_crm.service import CRMService
from test_stage2_offline import OWNER, accept, ru_service
from test_stage2_openai import OWNER as AI_OWNER, frame, output, save, setup


def add_noise(factory, clock):
    with factory.begin() as s:
        sources = [Source(id=uid(), owner_id=OWNER, channel="owner", account="noise", external_id=str(i)) for i in range(110)]
        s.add_all(sources)
        s.flush()
        versions = [SourceVersion(id=uid(), source_id=source.id, revision=1, text="Синтетический источник", status="processed") for source in sources]
        s.add_all(versions)
        s.flush()
        s.add_all(Task(owner_id=OWNER, source_version_id=v.id, title=f"Купить синтетический предмет {i}",
                       kind="task", state="active", version=1, created_at=clock() + timedelta(seconds=i+1)) for i,v in enumerate(versions))


@pytest.mark.parametrize("text", ["Резюме не обновил", "Резюме обновил?", "Резюме ещё не обновил",
                                 "Не выполнил задачу", "Последнее выполнил?", "Резюме обновил ли?"])
def test_uncertain_completion_keeps_task_and_reminder(ru_service, factory, text):
    task = accept(ru_service, "Завтра в 19:00 напомни обновить резюме")["task"]
    result = accept(ru_service, text, 2)
    assert result["status"] == "clarification"
    with factory() as s:
        assert s.get(Task, task["id"]).state == "active"
        assert s.get(Task, task["id"]).version == 1
        assert s.scalar(select(Reminder).where(Reminder.task_id == task["id"])).active
        assert s.scalar(select(func.count(History.id))) == 1


def test_time_only_answer_uses_saved_date_after_restart_and_midnight(ru_service, factory, clock):
    clock.now = datetime(2026, 10, 13, 20, 59, tzinfo=UTC)
    assert accept(ru_service, "Завтра напомни обновить резюме")["status"] == "clarification"
    clock.now += timedelta(minutes=2)
    restarted = CRMService(factory, ru_service.interpreter, clock)
    result = accept(restarted, "в 19:00", 2)
    assert result["status"] == "created"
    with factory() as s:
        assert s.scalar(select(Reminder)).at == datetime(2026, 10, 14, 16, tzinfo=UTC)
        assert s.scalar(select(Dialogue)).status == "resolved"
        assert s.scalar(select(func.count(Task.id))) == 1


def test_invalid_time_keeps_pending_date_for_next_answer(ru_service, factory):
    accept(ru_service, "Завтра напомни обновить резюме")
    assert accept(ru_service, "в 29:00", 2)["status"] == "clarification"
    assert accept(ru_service, "в 19:00", 3)["status"] == "created"


def test_subject_search_finds_old_task_beyond_65_rows(ru_service, factory, clock):
    task = accept(ru_service, "Надо обновить резюме")["task"]
    add_noise(factory, clock)
    result = accept(ru_service, "Резюме обновил", 2)
    assert result["status"] == "changed" and result["task"]["id"] == task["id"]
    with factory() as s:
        assert s.scalar(select(func.count(Task.id)).where(Task.state == "done")) == 1


def test_last_cursor_finds_old_reminder_outside_recent_candidates(ru_service, factory, clock):
    task = accept(ru_service, "Завтра в 19:00 напомни обновить резюме")["task"]
    add_noise(factory, clock)
    result = accept(ru_service, "Перенеси последнее напоминание на субботу", 2)
    assert result["status"] == "changed" and result["task"]["id"] == task["id"]


def test_edit_reminder_changes_reminder_after_confirmation(ru_service, factory):
    task = accept(ru_service, "Завтра в 19:00 напомни обновить резюме")["task"]
    proposal = accept(ru_service, "Завтра в 20:00 напомни обновить резюме", 2, edited=True)
    assert proposal["status"] == "proposal"
    assert proposal["proposal"]["change"] == "reminder"
    with factory() as s:
        assert s.scalar(select(Reminder).where(Reminder.active.is_(True))).at == datetime(2026, 10, 14, 16, tzinfo=UTC)
    result = ru_service.confirm(OWNER, proposal["proposal_id"], proposal["version"])
    assert result["task"]["title"] == task["title"]
    assert result["task"]["deadline"] is None
    with factory() as s:
        active = s.scalar(select(Reminder).where(Reminder.active.is_(True)))
        assert active.at == datetime(2026, 10, 14, 17, tzinfo=UTC)
        assert s.scalar(select(Job).where(Job.reminder_id == active.id)).status == "pending"
        assert s.scalar(select(func.count(Task.id))) == 1


def test_known_unbilled_provider_error_allows_explicit_retry(factory, clock):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx2.Response(401, json={"error": {"message": "synthetic denied", "type": "invalid_api_key"}})
        source = json.loads(json.loads(request.content)["input"][0]["content"])["source_version_id"]
        return httpx2.Response(200, json=frame(output(source)))
    service, adapter = setup(factory, clock, handler)
    source = save(service)
    assert service.process(AI_OWNER, source)["code"] == "ai_auth_error"
    assert adapter.ledger.status(AI_OWNER)["spent_micro_usd"] == 0
    assert service.process(AI_OWNER, source)["status"] == "created"
    assert len(calls) == 2
    assert adapter.ledger.status(AI_OWNER)["spent_micro_usd"] == 190


def test_recovery_picks_pending_source_without_telegram_replay(ru_service, factory):
    from personal_crm.schema import Incoming
    source = ru_service.ingest(OWNER, "owner", Incoming(external_id="persisted", account="offline",
                                                       text="Надо обновить резюме"))
    assert ru_service.recover_sources(OWNER) == {"processed": 1}
    assert ru_service.recover_sources(OWNER) == {"processed": 0}
    with factory() as s:
        assert s.get(SourceVersion, source).status == "processed"
        assert s.scalar(select(func.count(Task.id))) == 1


def test_recovery_reclaims_expired_parse_after_restart(ru_service, factory, clock):
    from personal_crm.schema import Incoming
    source = ru_service.ingest(OWNER, "owner", Incoming(external_id="leased", account="offline",
                                                       text="Надо обновить резюме"))
    with factory.begin() as s:
        version = s.get(SourceVersion, source)
        version.status, version.parse_token, version.parse_until = "processing", "dead-process", clock() - timedelta(seconds=1)
    restarted = CRMService(factory, ru_service.interpreter, clock)
    assert restarted.recover_sources(OWNER) == {"processed": 1}
    with factory() as s:
        assert s.get(SourceVersion, source).parse_token is None


def test_transient_processing_failure_recovers_with_bounded_backoff(ru_service, factory, clock):
    from personal_crm.schema import Incoming, Interpretation
    class TemporaryFailure:
        calls = 0
        def interpret_context(self, context):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("synthetic temporary failure")
            return Interpretation(source_version_id=context.source_version_id, operation="create", title="Синтетическая проверка", obvious=True)
    provider = TemporaryFailure()
    ru_service.interpreter = provider
    source = ru_service.ingest(OWNER, "owner", Incoming(external_id="transient", account="offline", text="Синтетическая нестандартная фраза"))
    assert ru_service.process(OWNER, source)["status"] == "error"
    assert ru_service.recover_sources(OWNER)["processed"] == 0
    clock.now += timedelta(seconds=61)
    assert ru_service.recover_sources(OWNER)["processed"] == 1
    assert provider.calls == 2


def test_permanent_processing_failure_stops_automatic_retries(ru_service, factory, clock):
    from personal_crm.schema import Incoming
    class Failing:
        calls = 0
        def interpret_context(self, context):
            self.calls += 1
            raise RuntimeError("synthetic permanent failure")
    provider = Failing()
    ru_service.interpreter = provider
    source = ru_service.ingest(OWNER, "owner", Incoming(external_id="permanent", account="offline", text="Синтетическая нестандартная фраза"))
    ru_service.process(OWNER, source)
    for _ in range(7):
        clock.now += timedelta(minutes=10)
        ru_service.recover_sources(OWNER)
    assert provider.calls == 3
    with factory() as s:
        assert s.get(SourceVersion, source).text
        assert s.get(SourceVersion, source).status == "error"


def test_edited_title_and_time_apply_together_only_after_confirmation(ru_service, factory):
    task = accept(ru_service, "Завтра в 19:00 напомни обновить резюме")["task"]
    proposal = accept(ru_service, "Завтра в 20:00 напомни подготовить учебный отчёт", 2, edited=True)
    with factory() as s:
        assert s.get(Task, task["id"]).title == task["title"]
    ru_service.confirm(OWNER, proposal["proposal_id"], proposal["version"])
    with factory() as s:
        assert s.get(Task, task["id"]).title == "подготовить учебный отчёт"
        assert s.scalar(select(Reminder).where(Reminder.active.is_(True))).at == datetime(2026, 10, 14, 17, tzinfo=UTC)


def test_explicit_reply_finds_question_beyond_context_cap(ru_service, factory):
    accept(ru_service, "Завтра напомни обновить резюме")
    for i in range(2, 14):
        accept(ru_service, "Завтра напомни подготовить учебный отчёт", i)
    result = accept(ru_service, "Завтра в 19:00", 14, reply_to=13)
    assert result["status"] == "created" and result["task"]["title"] == "подготовить учебный отчёт"


def test_uncertain_paid_request_never_repeats_in_recovery(factory, clock):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx2.ReadTimeout("synthetic unknown result", request=request)
    service, adapter = setup(factory, clock, handler)
    source = save(service)
    assert service.process(AI_OWNER, source)["code"] == "ai_timeout"
    for _ in range(5):
        clock.now += timedelta(minutes=10)
        service.recover_sources(AI_OWNER)
    assert service.process(AI_OWNER, source)["code"] == "ai_previous_attempt"
    assert len(calls) == 1
    assert adapter.ledger.status(AI_OWNER)["spent_micro_usd"] == 21024


def test_recovery_cli_runs_in_new_process(ru_service, factory):
    import os
    import subprocess
    import sys
    from personal_crm.schema import Incoming
    source = ru_service.ingest(OWNER, "owner", Incoming(external_id="new-process", account="offline", text="Надо обновить резюме"))
    result = subprocess.run([sys.executable, "-m", "personal_crm.source_worker", "--once"], env={**os.environ,
        "CRM_DATABASE_URL": os.environ["CRM_TEST_DATABASE_URL"], "CRM_OWNER_ID": OWNER,
        "CRM_OWNER_TOKEN": "synthetic-owner-credential", "CRM_TIMEZONE": "Europe/Moscow",
        "CRM_OPENAI_ENABLED": "false"}, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    with factory() as s:
        assert s.get(SourceVersion, source).status == "processed"


def test_rate_limit_automatically_retries_once_after_backoff(factory, clock):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx2.Response(429, json={"error": {"message": "synthetic rate limit", "type": "rate_limit_error"}})
        source = json.loads(json.loads(request.content)["input"][0]["content"])["source_version_id"]
        return httpx2.Response(200, json=frame(output(source)))
    service, adapter = setup(factory, clock, handler)
    source = save(service)
    assert service.process(AI_OWNER, source)["code"] == "ai_rate_limit"
    assert service.recover_sources(AI_OWNER)["processed"] == 0
    clock.now += timedelta(seconds=61)
    assert service.recover_sources(AI_OWNER)["processed"] == 1
    assert len(calls) == 2
    assert adapter.ledger.status(AI_OWNER)["spent_micro_usd"] == 190


@pytest.mark.parametrize("setting,code", [("pause", "ai_disabled"), ("cap", "ai_budget_limit")])
def test_owner_preferences_block_paid_request_before_client_creation(factory, clock, setting, code):
    from personal_crm.models import Profile
    def forbidden(request):
        pytest.fail("Owner preference must block SDK invocation")
    service, adapter = setup(factory, clock, forbidden)
    with factory.begin() as s:
        profile = s.get(Profile, AI_OWNER)
        if setting == "pause":
            profile.ai_paused = True
        else:
            profile.ai_budget_cap_micro_usd = 0
    source = save(service)
    assert service.process(AI_OWNER, source)["code"] == code


def test_edit_original_after_short_clarification_keeps_one_task(ru_service, factory):
    origin = accept(ru_service, "Завтра напомни обновить резюме")
    created = accept(ru_service, "в 19:00", 2)
    assert created["status"] == "created"
    edit = accept(ru_service, "Завтра в 20:00 напомни обновить резюме", 3, edited=True)
    assert edit["status"] == "proposal" and edit["proposal"]["target_id"] == created["task"]["id"]
    with factory() as s:
        assert s.get(Task, created["task"]["id"]).source_version_id == origin["source_version_id"]
        assert s.scalar(select(func.count(Task.id))) == 1


def test_concurrent_answers_resolve_creation_once(ru_service, factory, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import personal_crm.language as language
    from personal_crm.schema import Incoming
    origin = accept(ru_service, "Завтра напомни обновить резюме")
    answers = [ru_service.ingest(OWNER, "owner", Incoming(external_id=f"answer-{i}", account="telegram:303:202", text="в 19:00"),
        metadata={"reply_source_version_id": origin["source_version_id"]}) for i in range(2)]
    barrier = Barrier(2)
    deterministic = language.deterministic
    def concurrent(context):
        result = deterministic(context)
        if result and result.operation == "create" and result.dialogue_id:
            barrier.wait(5)
        return result
    monkeypatch.setattr(language, "deterministic", concurrent)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda identity: ru_service.process(OWNER, identity), answers))
    assert sorted(r["status"] for r in results) == ["conflict", "created"]
    with factory() as s:
        assert s.scalar(select(func.count(Task.id))) == 1
