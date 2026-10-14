from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from personal_crm.api import create_app
from personal_crm.config import Settings
from personal_crm.models import Profile, Reminder, Task
from test_stage2_offline import OWNER, ru_service

AUTH = {"Authorization": "Bearer synthetic-web-secret"}


@pytest.fixture
def web(factory, clock, ru_service):
    settings = Settings(factory.kw["bind"].url.render_as_string(hide_password=False), OWNER,
                        "synthetic-web-secret", timezone="Europe/Moscow")
    app = create_app(settings, ru_service.interpreter)
    app.state.service.clock = clock
    return TestClient(app)


def create(web, **changes):
    data = {"request_id": "synthetic-web-1", "title": "Произвольное ручное дело", **changes}
    response = web.post("/workspace/tasks", headers=AUTH, json=data)
    assert response.status_code == 200, response.text
    return response.json()


def test_manual_create_search_detail_and_idempotency(web, factory):
    task = create(web, reminder_local="2026-10-15T19:00", planned_on="2026-10-15")
    assert create(web, reminder_local="2026-10-15T19:00", planned_on="2026-10-15")["id"] == task["id"]
    assert web.get("/workspace/tasks").status_code == 401
    search = web.get("/workspace/tasks?q=ручное&limit=1", headers=AUTH).json()
    assert search["total"] == 1 and search["items"][0]["id"] == task["id"]
    detail = web.get(f"/workspace/tasks/{task['id']}", headers=AUTH).json()
    assert detail["source"]["text"] and detail["reminder_at"]
    assert len(detail["history"]) == 1
    with factory() as s:
        assert s.scalar(select(Reminder)).at == datetime(2026, 10, 15, 16, tzinfo=UTC)
    assert web.post("/workspace/tasks", headers=AUTH, json={"request_id": "synthetic-web-1", "title": "Другая правка"}).status_code == 409


def test_workspace_edit_versions_and_separate_fields(web, factory):
    task = create(web, reminder_local="2026-10-15T19:00", planned_on="2026-10-15", deadline={
        "precision": "date", "value": "2026-10-20", "original": "2026-10-20", "timezone": "Europe/Moscow"})
    path = f"/workspace/tasks/{task['id']}"
    updated = web.patch(path, headers=AUTH, json={"version": 1, "title": "Новое название", "reminder_local": "2026-10-15T20:00"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["planned_on"] == "2026-10-15" and updated.json()["deadline"]["value"] == "2026-10-20"
    assert web.patch(path, headers=AUTH, json={"version": 1, "title": "Устаревшая правка"}).status_code == 409
    cleared = web.patch(path, headers=AUTH, json={"version": updated.json()["version"], "reminder_local": None, "planned_on": None})
    assert cleared.status_code == 200 and cleared.json()["planned_on"] is None
    with factory() as s:
        assert not s.scalar(select(Reminder).where(Reminder.active.is_(True)))


def test_projects_group_tasks_and_reject_foreign_objects(web, factory, clock, ru_service):
    response = web.post("/workspace/projects", headers=AUTH, json={"name": "Учебный проект", "description": "Синтетическое описание"})
    assert response.status_code == 200, response.text
    project = response.json()
    task = create(web, project_id=project["id"])
    assert web.get(f"/workspace/tasks?project_id={project['id']}", headers=AUTH).json()["total"] == 1
    projects = web.get("/workspace/projects", headers=AUTH).json()
    assert projects[0]["active_tasks"] == 1
    foreign = Settings(factory.kw["bind"].url.render_as_string(hide_password=False), "synthetic-other-web-owner", "synthetic-other-secret", timezone="UTC")
    other = TestClient(create_app(foreign, ru_service.interpreter))
    headers = {"Authorization": "Bearer synthetic-other-secret"}
    assert other.get(f"/workspace/tasks/{task['id']}", headers=headers).status_code == 404
    assert other.patch(f"/workspace/projects/{project['id']}", headers=headers, json={"version": 1, "name": "Чужая правка"}).status_code == 404
    assert other.post("/workspace/tasks", headers=headers, json={"request_id": "foreign", "title": "Дело", "project_id": project["id"]}).status_code == 404


def test_settings_survive_new_requests_and_conflicts(web, factory):
    original = web.get("/workspace/settings", headers=AUTH)
    assert original.status_code == 200
    settings = original.json()
    updated = web.patch("/workspace/settings", headers=AUTH, json={"version": settings["version"], "timezone": "Europe/Berlin", "digest_hour": 9, "initiative_limit": 1})
    assert updated.status_code == 200, updated.text
    assert web.get("/workspace/settings", headers=AUTH).json()["timezone"] == "Europe/Berlin"
    assert web.patch("/workspace/settings", headers=AUTH, json={"version": settings["version"], "digest_hour": 10}).status_code == 409
    assert web.patch("/workspace/settings", headers=AUTH, json={"version": updated.json()["version"], "timezone": "Invalid/Timezone"}).status_code == 422


def test_inbox_clarification_reply_uses_real_context(web, factory):
    raw = web.post("/sources", headers=AUTH, json={"external_id": "clarify-web", "account": "web", "text": "Завтра напомни обновить резюме"}).json()
    assert raw["status"] == "clarification"
    inbox = web.get("/workspace/inbox", headers=AUTH).json()
    assert len(inbox["questions"]) == 1
    reply = web.post(f"/workspace/sources/{raw['source_version_id']}/reply", headers=AUTH, json={"request_id": "reply-one", "text": "в 19:00"})
    assert reply.status_code == 200 and reply.json()["status"] == "created"
    assert web.get("/workspace/inbox", headers=AUTH).json()["questions"] == []


def test_workspace_filters_pagination_and_sql_wildcards(web):
    create(web, title="100% готово", request_id="one")
    create(web, title="1000 дел", request_id="two", kind="note")
    assert web.get("/workspace/tasks?q=%25", headers=AUTH).json()["total"] == 1
    assert web.get("/workspace/tasks?kind=note", headers=AUTH).json()["total"] == 1
    page = web.get("/workspace/tasks?offset=1&limit=1", headers=AUTH).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert web.get("/workspace/tasks?state=invalid", headers=AUTH).status_code == 422
    assert web.get("/workspace/tasks?limit=10000", headers=AUTH).status_code == 422


def test_manual_invalid_or_dst_ambiguous_reminder_never_creates_task(web, factory):
    response = web.post("/workspace/tasks", headers=AUTH, json={"request_id": "bad", "title": "Дело", "reminder_local": "2026-10-15T29:00"})
    assert response.status_code == 422
    with factory() as s:
        assert list(s.scalars(select(Task))) == []


def test_deadline_local_distinguishes_date_and_instant(web):
    task = create(web, deadline_local="2026-10-20")
    assert task["deadline"]["precision"] == "date" and task["deadline"]["value"] == "2026-10-20"
    updated = web.patch(f"/workspace/tasks/{task['id']}", headers=AUTH,
        json={"version": task["version"], "deadline_local": "2026-10-20T19:00"})
    assert updated.status_code == 200 and updated.json()["deadline"]["precision"] == "instant"
    assert datetime.fromisoformat(updated.json()["deadline"]["value"]) == datetime(2026, 10, 20, 16, tzinfo=UTC)


def test_undated_filter_returns_only_tasks_without_deadlines(web):
    create(web, request_id="undated")
    create(web, request_id="dated", deadline={"precision":"date", "value":"2026-10-20", "original":"2026-10-20", "timezone":"Europe/Moscow"})
    page = web.get("/workspace/tasks?undated=true", headers=AUTH).json()
    assert page["total"] == 1 and page["items"][0]["deadline"] is None


def test_deadline_filters_use_current_time_and_stored_timezone(web):
    create(web, request_id="past", deadline_local="2026-10-12")
    create(web, request_id="future", deadline_local="2026-11-01T19:00")
    create(web, request_id="none")
    for mode in ("overdue", "upcoming", "none"):
        page = web.get(f"/workspace/tasks?deadline={mode}", headers=AUTH)
        assert page.status_code == 200 and page.json()["total"] == 1


def test_unicode_case_insensitive_search(web):
    create(web, title="Обновить РЕЗЮМЕ")
    page = web.get("/workspace/tasks?q=резюме", headers=AUTH).json()
    assert page["total"] == 1


def test_preferences_can_pause_ai_and_cap_budget_without_enabling_provider(web):
    current = web.get("/workspace/settings", headers=AUTH).json()
    response = web.patch("/workspace/settings", headers=AUTH, json={"version": current["version"], "ai_paused": True, "ai_budget_cap_micro_usd": 0})
    assert response.status_code == 200 and response.json()["ai_paused"] is True
    assert response.json()["integrations"]["openai"] is False
    assert response.json()["ai_budget_cap_micro_usd"] == 0
    rejected = web.patch("/workspace/settings", headers=AUTH, json={"version": response.json()["version"], "ai_budget_cap_micro_usd": 1_000_000})
    assert rejected.status_code == 422


def test_multi_field_web_edit_rolls_back_on_invalid_time(web, factory):
    task = create(web, reminder_local="2026-10-15T19:00")
    response = web.patch(f"/workspace/tasks/{task['id']}", headers=AUTH,
        json={"version": 1, "title": "Нельзя применить частично", "reminder_local": "2026-10-15T29:00"})
    assert response.status_code == 422
    with factory() as s:
        current = s.get(Task, task["id"])
        assert current.title == task["title"] and current.version == 1
        assert s.scalar(select(Reminder).where(Reminder.active.is_(True))).at == datetime(2026, 10, 15, 16, tzinfo=UTC)


def test_web_requests_have_browser_security_headers(web):
    response = web.get("/workspace/settings", headers=AUTH)
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert "frame-ancestors 'none'" in response.headers.get("content-security-policy", "")


def test_manual_creation_records_owner_in_history(web):
    task = create(web)
    history = web.get(f"/tasks/{task['id']}/history", headers=AUTH).json()
    assert history[0]["actor"] == "owner"


def test_access_log_excludes_search_text(web, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d',
            "synthetic-client", "GET", "/workspace/tasks?q=synthetic-private-query", "1.1", 200)
    assert "synthetic-private-query" not in caplog.text
    assert "/workspace/tasks" in caplog.text
