"""Stage D: calendar series and confirmed plans over real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from personal_crm.api import create_app
from personal_crm.config import Settings
from personal_crm.models import History, Job, Profile, Reminder, Task
from personal_crm.schema import Incoming

OWNER = "synthetic-owner"
AUTH = {"Authorization": "Bearer synthetic-stage-d"}


@pytest.fixture
def web(factory, service, clock):
    settings = Settings(factory.kw["bind"].url.render_as_string(hide_password=False), OWNER,
                        "synthetic-stage-d", timezone="Europe/Berlin")
    app = create_app(settings, service.interpreter)
    app.state.service.clock = clock
    return TestClient(app)


def create(web, title="Синтетическая регулярная проверка", **values):
    result = web.post("/workspace/tasks", headers=AUTH,
                      json={"request_id": title, "title": title, **values})
    assert result.status_code == 200, result.text
    return result.json()


def recur(web, task, **values):
    result = web.post(f"/workspace/tasks/{task['id']}/recurrence", headers=AUTH,
                      json={"version": task["version"], "frequency": "daily", "interval": 1,
                            "anchor_on": "2026-10-13", "reminder_time": None, **values})
    assert result.status_code == 200, result.text
    return result.json()


def command(web, task, action="close"):
    result = web.post(f"/tasks/{task['id']}/commands", headers=AUTH,
                      json={"version": task["version"], "action": action})
    assert result.status_code == 200, result.text
    return result.json()


def test_completion_creates_one_future_occurrence_preserves_rule_and_no_deadline(web, factory, clock):
    initial = create(web)
    result = recur(web, initial, reminder_time="19:00")
    current = result["task"]
    assert current["recurrence_id"] == result["rule"]["id"]
    command(web, current)
    tasks = web.get("/workspace/tasks", headers=AUTH).json()["items"]
    assert len(tasks) == 2
    future = next(t for t in tasks if t["state"] == "active")
    assert future["occurrence_on"] == "2026-10-14" and future["deadline"] is None
    assert datetime.fromisoformat(future["reminder_at"]) == datetime(2026, 10, 14, 17, tzinfo=UTC)
    assert not web.get("/overview", headers=AUTH).json()["main"]
    clock.now += timedelta(days=1)
    assert web.get("/overview", headers=AUTH).json()["main"][0]["id"] == future["id"]
    with factory() as s:
        assert all(j.status == "cancelled" for j in s.scalars(select(Job).join(Reminder).where(Reminder.task_id == current["id"])))


@pytest.mark.parametrize("frequency,anchor,after,expected", [
    ("monthly", "2026-01-31", "2026-02-28", "2026-03-31"),
    ("monthly", "2028-01-31", "2028-01-31", "2028-02-29"),
    ("weekly", "2026-10-13", "2026-11-10", "2026-11-17"),
    ("daily", "2026-10-13", "2026-11-10", "2026-11-11"),
])
def test_calendar_anchor_and_missed_periods_do_not_create_a_backlog(web, clock, frequency, anchor, after, expected):
    clock.now = datetime.fromisoformat(after + "T08:00:00+00:00")
    current = recur(web, create(web), frequency=frequency, anchor_on=anchor)["task"]
    command(web, current)
    tasks = web.get("/workspace/tasks", headers=AUTH).json()["items"]
    assert len(tasks) == 2
    assert next(t for t in tasks if t["state"] == "active")["occurrence_on"] == expected


def test_dst_gap_is_visible_and_does_not_silently_shift_notification(web, clock):
    clock.now = datetime(2026, 3, 28, 8, tzinfo=UTC)
    result = recur(web, create(web), anchor_on="2026-03-28", reminder_time="02:30")
    command(web, result["task"])
    future = web.get("/workspace/tasks?state=active", headers=AUTH).json()["items"][0]
    assert future["occurrence_on"] == "2026-03-29" and future["reminder_at"] is None
    assert future["recurrence_warning"] == "ambiguous_or_invalid_time"


def test_cancel_occurrence_and_stop_series_are_different_explicit_actions(web):
    result = recur(web, create(web))
    command(web, result["task"], "cancel")
    next_task = web.get("/workspace/tasks?state=active", headers=AUTH).json()["items"][0]
    rule = web.get(f"/workspace/tasks/{next_task['id']}", headers=AUTH).json()["recurrence"]
    stopped = web.patch(f"/workspace/recurrences/{rule['id']}", headers=AUTH, json={"version": rule["version"], "status": "stopped"})
    assert stopped.status_code == 200, stopped.text
    assert web.get("/workspace/tasks?state=active", headers=AUTH).json()["items"][0]["state"] == "active"
    command(web, next_task)
    assert web.get("/workspace/tasks?state=active", headers=AUTH).json()["total"] == 0


def test_two_competing_completions_create_one_instance(web, factory):
    current = recur(web, create(web))["task"]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: web.post(f"/tasks/{current['id']}/commands", headers=AUTH,
            json={"version": current["version"], "action": "close"}).status_code, range(2)))
    assert sorted(results) == [200, 409]
    with factory() as s:
        assert len(s.scalars(select(Task)).all()) == 2


def test_next_instance_history_failure_rolls_back_completion(web, factory):
    current = recur(web, create(web))["task"]
    with factory.begin() as s:
        s.execute(text("ALTER TABLE history ADD CONSTRAINT test_recurrence_failure CHECK (reason <> 'recurrence_occurrence')"))
    try:
        result = web.post(f"/tasks/{current['id']}/commands", headers=AUTH, json={"version": current["version"], "action": "close"})
        assert result.status_code == 503
        with factory() as s:
            assert s.get(Task, current["id"]).state == "active"
            assert len(s.scalars(select(Task)).all()) == 1
    finally:
        with factory.begin() as s:
            s.execute(text("ALTER TABLE history DROP CONSTRAINT test_recurrence_failure"))


def test_steps_are_drafts_until_whole_plan_confirmation_and_replay_is_idempotent(web, factory):
    parent = create(web)
    result = web.put(f"/workspace/tasks/{parent['id']}/steps", headers=AUTH,
                     json={"version": parent["version"], "steps": ["Открыть учебный файл", "Проверить итог"]})
    assert result.status_code == 200, result.text
    parent = result.json()
    assert web.get("/workspace/tasks", headers=AUTH).json()["total"] == 1
    path = f"/workspace/tasks/{parent['id']}/steps/confirm"
    body = {"version": parent["version"], "request_id": "synthetic-plan-confirm"}
    result = web.post(path, headers=AUTH, json=body)
    assert result.status_code == 200, result.text
    assert result.json() == web.post(path, headers=AUTH, json=body).json()
    with factory() as s:
        children = s.scalars(select(Task).where(Task.parent_task_id == parent["id"])).all()
        assert len(children) == 2 and all(t.deadline is None and t.planned_on is None for t in children)
        assert not s.scalar(select(Reminder))
        assert s.get(Task, parent["id"]).state == "active"


def test_stale_plan_confirmation_cannot_promote_new_steps(web):
    parent = create(web)
    path = f"/workspace/tasks/{parent['id']}/steps"
    parent = web.put(path, headers=AUTH, json={"version": parent["version"], "steps": ["Первый вариант"]}).json()
    old_version = parent["version"]
    changed = web.put(path, headers=AUTH, json={"version": old_version, "steps": ["Новый вариант"]})
    assert changed.status_code == 200
    result = web.post(path + "/confirm", headers=AUTH, json={"version": old_version, "request_id": "synthetic-stale-plan"})
    assert result.status_code == 409
    assert web.get("/workspace/tasks", headers=AUTH).json()["total"] == 1


def test_early_plan_requires_confirmation_and_preserves_the_external_deadline(web):
    task = create(web, deadline={"precision": "date", "value": "2026-10-20", "original": "2026-10-20", "timezone": "Europe/Berlin"})
    result = web.post("/workspace/suggestions/refresh", headers=AUTH)
    assert result.status_code == 200, result.text
    early = next(p for p in result.json()["items"] if p["kind"] == "early")
    current = web.get(f"/workspace/tasks/{task['id']}", headers=AUTH).json()
    assert current["planned_on"] is None
    confirmed = web.post(f"/workspace/suggestions/{early['id']}/confirm", headers=AUTH, json={"version": early["version"], "accept": True})
    assert confirmed.status_code == 200, confirmed.text
    current = web.get(f"/workspace/tasks/{task['id']}", headers=AUTH).json()
    assert current["planned_on"] == "2026-10-18" and current["deadline"] == task["deadline"]


def test_small_step_only_starts_after_confirmation_and_does_not_create_subtasks(web, factory):
    task = create(web)
    response = web.post("/workspace/suggestions/refresh", headers=AUTH)
    assert response.status_code == 200, response.text
    step = next(p for p in response.json()["items"] if p["kind"] == "step")
    assert step["payload"]["step"]
    assert web.get(f"/workspace/tasks/{task['id']}", headers=AUTH).json()["state"] == "active"
    result = web.post(f"/workspace/suggestions/{step['id']}/confirm", headers=AUTH, json={"version": step["version"], "accept": True})
    assert result.status_code == 200, result.text
    with factory() as s:
        assert s.get(Task, task["id"]).state == "in_progress" and len(s.scalars(select(Task)).all()) == 1


def test_suggestion_is_version_bound_and_dismissal_is_not_regenerated(web):
    task = create(web)
    response = web.post("/workspace/suggestions/refresh", headers=AUTH)
    assert response.status_code == 200, response.text
    step = next(p for p in response.json()["items"] if p["kind"] == "step")
    web.patch(f"/workspace/tasks/{task['id']}", headers=AUTH, json={"version": task["version"], "title": "Исправленное дело"})
    assert web.post(f"/workspace/suggestions/{step['id']}/confirm", headers=AUTH, json={"version": step["version"], "accept": True}).status_code == 409
    step = web.post("/workspace/suggestions/refresh", headers=AUTH).json()["items"][0]
    assert web.post(f"/workspace/suggestions/{step['id']}/confirm", headers=AUTH, json={"version": step["version"], "accept": False}).status_code == 200
    assert web.post("/workspace/suggestions/refresh", headers=AUTH).json()["items"] == []


def test_adaptation_uses_explicit_choices_and_never_moves_existing_reminders(web, factory):
    for n in range(3):
        create(web, title=f"Синтетический ручной выбор {n}", reminder_local=f"2026-10-{14+n}T19:00")
    with factory() as s:
        original = {r.id: r.at for r in s.scalars(select(Reminder))}
    response = web.post("/workspace/suggestions/refresh", headers=AUTH)
    assert response.status_code == 200, response.text
    suggestion = next(p for p in response.json()["items"] if p["kind"] == "reminder_time")
    assert suggestion["payload"]["reminder_time"] == "19:00"
    with factory() as s:
        assert s.get(Profile, OWNER).preferred_reminder_time is None
    confirmed = web.post(f"/workspace/suggestions/{suggestion['id']}/confirm", headers=AUTH,
                         json={"version": suggestion["version"], "accept": True})
    assert confirmed.status_code == 200, confirmed.text
    with factory() as s:
        profile = s.get(Profile, OWNER)
        assert profile.preferred_reminder_time == "19:00" and profile.initiative_limit == 2
        assert original == {r.id: r.at for r in s.scalars(select(Reminder))}


def test_manually_selected_preference_is_not_overridden_by_adaptation(web):
    prefs = web.get("/workspace/settings", headers=AUTH).json()
    response = web.patch("/workspace/settings", headers=AUTH, json={"version": prefs["version"], "preferred_reminder_time": "08:30"})
    assert response.status_code == 200, response.text
    for n in range(3):
        create(web, title=f"Учебный повторный выбор {n}", reminder_local=f"2026-10-{14+n}T19:00")
    assert not any(p["kind"] == "reminder_time" for p in web.post("/workspace/suggestions/refresh", headers=AUTH).json()["items"])


def test_model_changes_to_existing_step_plan_require_confirmation(web, factory):
    task = create(web)
    service = web.app.state.service
    service.interpreter.fixtures["synthetic proposed new plan"] = {"operation": "propose_update", "target_id": task["id"],
        "target_version": task["version"], "change": "steps", "draft_steps": ["Открыть учебный файл", "Сверить итог"]}
    identity = service.ingest(OWNER, "forward", Incoming(account="synthetic-plan", external_id="new-steps", text="synthetic proposed new plan"))
    result = service.process(OWNER, identity)
    assert result["status"] == "proposal"
    with factory() as s:
        assert s.get(Task, task["id"]).draft_steps == []
    response = web.post(f"/proposals/{result['proposal_id']}/confirm", headers=AUTH, json={"version": 1, "accept": True})
    assert response.status_code == 200, response.text
    with factory() as s:
        assert s.get(Task, task["id"]).draft_steps == ["Открыть учебный файл", "Сверить итог"]
        assert len(s.scalars(select(Task)).all()) == 1


def test_recurring_template_edits_leave_current_task_and_reminder_unchanged(web):
    result = recur(web, create(web), reminder_time="19:00")
    task, rule = result["task"], result["rule"]
    response = web.patch(f"/workspace/recurrences/{rule['id']}", headers=AUTH,
        json={"version": rule["version"], "title": "Новое учебное повторение", "reminder_time": "20:00", "frequency": "weekly", "interval": 2})
    assert response.status_code == 200, response.text
    current = web.get(f"/workspace/tasks/{task['id']}", headers=AUTH).json()
    assert current["title"] == task["title"] and current["reminder_at"] == task["reminder_at"]
    command(web, current)
    future = web.get("/workspace/tasks?state=active", headers=AUTH).json()["items"][0]
    assert future["title"] == "Новое учебное повторение" and future["occurrence_on"] == "2026-10-27"


def test_unrelated_owner_cannot_use_rules_steps_or_suggestions(web, factory, service):
    result = recur(web, create(web))
    owner2 = "synthetic-stage-d-outsider"
    service.register(owner2, "UTC")
    app = create_app(Settings(factory.kw["bind"].url.render_as_string(hide_password=False), owner2, "synthetic-stage-d"), service.interpreter)
    other = TestClient(app)
    assert other.patch(f"/workspace/recurrences/{result['rule']['id']}", headers=AUTH,
                       json={"version": 1, "status": "stopped"}).status_code == 404
    assert other.put(f"/workspace/tasks/{result['task']['id']}/steps", headers=AUTH,
                     json={"version": 2, "steps": ["Чужой шаг"]}).status_code == 404
    suggestion = web.post("/workspace/suggestions/refresh", headers=AUTH).json()["items"][0]
    assert other.post(f"/workspace/suggestions/{suggestion['id']}/confirm", headers=AUTH,
                      json={"version": suggestion["version"], "accept": True}).status_code == 404


def test_repeated_generic_completion_does_not_close_tomorrows_instance(web, factory, service, clock):
    from personal_crm.openai_adapter import ContextInterpreter
    from personal_crm.service import CRMService
    task = recur(web, create(web))["task"]
    command(web, task)
    conversational = CRMService(factory, ContextInterpreter(service.interpreter), clock)
    identity = conversational.ingest(OWNER, "owner", Incoming(account="synthetic-recurring-commands",
        external_id="repeated-generic-done", text="выполнил"))
    result = conversational.process(OWNER, identity)
    assert result["status"] == "clarification"
    with factory() as s:
        assert len(s.scalars(select(Task)).all()) == 2


def test_preference_only_daily_overview_is_not_silently_empty(web):
    from personal_crm.accompaniment import render_overview
    for n in range(3):
        task = create(web, title=f"Учебный завершённый выбор {n}", reminder_local=f"2026-10-{14+n}T19:00")
        command(web, task)
    assert any(p["kind"] == "reminder_time" for p in web.post("/workspace/suggestions/refresh", headers=AUTH).json()["items"])
    overview = web.get("/overview", headers=AUTH).json()
    assert not overview["main"] and render_overview(overview) is not None


def test_early_planning_policy_is_server_configurable(web, factory, service, clock):
    from personal_crm.planning_config import PlanningPolicy
    task = create(web, deadline={"precision": "date", "value": "2026-10-23", "original": "2026-10-23", "timezone": "Europe/Berlin"})
    config = Settings(factory.kw["bind"].url.render_as_string(hide_password=False), OWNER, "synthetic-stage-d",
                      planning=PlanningPolicy(early_horizon_days=10, early_lead_days=3))
    app = create_app(config, service.interpreter); app.state.service.clock = clock
    suggestions = TestClient(app).post("/workspace/suggestions/refresh", headers=AUTH).json()["items"]
    early = next(p for p in suggestions if p["kind"] == "early" and p["task_id"] == task["id"])
    assert early["payload"]["planned_on"] == "2026-10-20"
