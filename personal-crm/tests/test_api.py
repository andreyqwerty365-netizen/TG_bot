from fastapi.testclient import TestClient
from sqlalchemy import func, select

from personal_crm.api import create_app
from personal_crm.config import Settings
from personal_crm.models import Source, Task


def client(factory, interpreter, **kwargs):
    settings = Settings(factory.kw["bind"].url.render_as_string(hide_password=False), "synthetic-owner", "synthetic-owner-credential",
                        "synthetic-connector-credential", "Europe/Berlin")
    if kwargs:
        from dataclasses import replace
        settings = replace(settings, **kwargs)
    return TestClient(create_app(settings, interpreter))


def test_owner_api_and_connector_authentication(factory, interpreter):
    api = client(factory, interpreter)
    body = {"external_id": "one", "account": "synthetic", "text": "synthetic task"}
    assert api.get("/health").status_code == 200
    assert api.get("/ready").status_code == 200
    assert api.get("/tasks").status_code == 401
    assert api.post("/sources", json=body).status_code == 401
    headers = {"Authorization": "Bearer synthetic-owner-credential"}
    result = api.post("/sources", json=body, headers=headers)
    assert result.status_code == 200 and result.json()["status"] == "created"
    assert len(api.get("/tasks", headers=headers).json()) == 1
    assert api.post("/sources", json={**body, "owner_id": "outsider"}, headers=headers).status_code == 422
    assert api.post("/sources", json={**body, "channel": "mail"}, headers=headers).status_code == 422
    assert api.post("/adapters/fake-mail", json=body, headers=headers).status_code == 401
    result = api.post("/adapters/fake-mail", json=body, headers={"X-Connector-Token": "synthetic-connector-credential"})
    assert result.json()["status"] == "proposal"
    assert api.post(f'/proposals/{result.json()["proposal_id"]}/confirm', json={"version": 1},
                    headers={"X-Connector-Token": "synthetic-connector-credential"}).status_code == 401


def test_missing_owner_fails_closed(factory, interpreter):
    api = client(factory, interpreter, owner_id="", owner_token="")
    assert api.get("/tasks").status_code == 503
    assert api.get("/ready").status_code == 503
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Source)) == 0


def test_http_reminder_and_close(factory, interpreter):
    api = client(factory, interpreter)
    headers = {"Authorization": "Bearer synthetic-owner-credential"}
    result = api.post("/sources", json={"external_id": "one", "account": "synthetic", "text": "synthetic task"},
                      headers=headers).json()
    task_id = result["task"]["id"]
    endpoint = f"/tasks/{task_id}/commands"
    assert api.post(endpoint, headers=headers, json={"version": 1, "action": "reminder", "at": "2026-10-13T12:00:00"}).status_code == 422
    assert api.post(endpoint, headers=headers, json={"version": 1, "action": "reminder", "at": "2026-10-13T12:00:00Z"}).status_code == 200
    assert api.post(endpoint, headers=headers, json={"version": 1, "action": "close"}).status_code == 409
    assert api.post(endpoint, headers=headers, json={"version": 2, "action": "close"}).json()["state"] == "done"


def test_database_error_never_acknowledged(factory, interpreter, monkeypatch):
    from sqlalchemy.exc import OperationalError
    api = client(factory, interpreter)
    def fail(*args, **kwargs):
        raise OperationalError("private query", {}, Exception("secret diagnostic"))
    monkeypatch.setattr(api.app.state.service, "ingest", fail)
    response = api.post("/sources", headers={"Authorization": "Bearer synthetic-owner-credential"},
                        json={"external_id": "one", "account": "synthetic", "text": "synthetic task"})
    assert response.status_code == 503 and response.json() == {"detail": "database_unavailable"}
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 0


def test_accompaniment_api_commands_overview_and_protected_history(factory, interpreter):
    api = client(factory, interpreter)
    headers = {"Authorization": "Bearer synthetic-owner-credential"}
    task = api.post("/sources", json={"external_id": "planning", "account": "synthetic", "text": "synthetic task"},
                    headers=headers).json()["task"]
    endpoint = f'/tasks/{task["id"]}/commands'
    task = api.post(endpoint, json={"version": 1, "action": "plan", "planned_on": "2026-10-20"}, headers=headers).json()
    assert task["planned_on"] == "2026-10-20" and task["deadline"] is None
    for day in (21, 22, 23):
        task = api.post(endpoint, json={"version": task["version"], "action": "plan", "planned_on": f"2026-10-{day}"},
                        headers=headers).json()
    view = api.get("/overview", headers=headers).json()
    assert view["guidance"][0]["kind"] == "obstacle"
    assert api.get("/guidance", headers=headers).json()[0]["status"] == "pending"
    assert len(api.get(f'/tasks/{task["id"]}/history', headers=headers).json()) == 5
    for path in ("/overview", "/guidance", "/deliveries", f'/tasks/{task["id"]}/history'):
        assert api.get(path).status_code == 401
    assert api.get("/tasks/nonexistent/history", headers=headers).status_code == 404
    assert api.post(endpoint, json={"version": task["version"], "action": "plan", "planned_on": "2026-02-30"},
                    headers=headers).status_code == 422
