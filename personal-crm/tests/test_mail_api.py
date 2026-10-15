from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from personal_crm.api import create_app
from personal_crm.config import Settings
from personal_crm.mail import MailPage, MailSync
from personal_crm.models import MailAccount, Proposal, SourceVersion, Task
from test_mail_sync import OWNER, Provider, item

AUTH = {"Authorization": "Bearer synthetic-mail-web-secret"}


@pytest.fixture
def web(factory, service, clock):
    provider = Provider(MailPage([item(clock)], {"position": 1}))
    config = Settings(factory.kw["bind"].url.render_as_string(hide_password=False), OWNER,
                      "synthetic-mail-web-secret", timezone="Europe/Moscow")
    app = create_app(config, service.interpreter, mail_provider=provider)
    app.state.service.clock = clock
    return TestClient(app), provider


def test_sync_status_evidence_and_explicit_confirmation(web, factory):
    client, provider = web
    assert client.get("/workspace/mail").status_code == 401
    status = client.get("/workspace/mail", headers=AUTH).json()
    assert status["available"] and status["read_only"] and status["window_days"] == 7
    assert client.post("/workspace/mail/sync", headers=AUTH).json()["saved"] == 1
    client.app.state.service.recover_sources(OWNER)
    inbox = client.get("/workspace/inbox", headers=AUTH).json()
    proposal = inbox["proposals"][0]
    assert proposal["evidence"]["subject"] == "Учебный отчёт"
    assert "Пожалуйста" in proposal["evidence"]["excerpt"]
    assert proposal["evidence"]["original_at"] and proposal["evidence"]["direction"] == "inbox"
    assert client.get("/workspace/tasks", headers=AUTH).json()["total"] == 0
    response = client.post(f"/proposals/{proposal['id']}/confirm", headers=AUTH, json={"version": 1, "accept": True})
    assert response.status_code == 200
    assert client.get("/workspace/tasks", headers=AUTH).json()["total"] == 1
    assert "synthetic-mail-web-secret" not in str(inbox)


def test_disabled_server_never_constructs_provider(factory, service, monkeypatch):
    def forbidden(*args):
        raise AssertionError("no network")
    monkeypatch.setattr("personal_crm.mail.build_provider", forbidden)
    settings = Settings(factory.kw["bind"].url.render_as_string(hide_password=False), OWNER,
                        "synthetic-mail-web-secret")
    client = TestClient(create_app(settings, service.interpreter))
    status = client.get("/workspace/mail", headers=AUTH).json()
    assert not status["available"] and status["status"] == "disabled"
    assert client.post("/workspace/mail/sync", headers=AUTH).status_code == 409


def test_disconnect_fences_out_inflight_and_error_visible_in_overview(web, factory, clock):
    client, provider = web
    client.post("/workspace/mail/sync", headers=AUTH)
    with factory.begin() as s:
        account = s.get(MailAccount, OWNER)
        account.status, account.error_code = "auth_error", "mail_auth_error"
    overview = client.get("/overview", headers=AUTH).json()
    assert overview["sync_errors"][0]["code"] == "mail_auth_error"
    assert client.post("/workspace/mail/disconnect", headers=AUTH).json()["status"] == "disabled"
    assert client.post("/workspace/mail/sync", headers=AUTH).json()["status"] == "disabled"


def test_manual_review_is_still_only_a_proposal(web, factory, clock):
    client, provider = web
    provider.pages = [MailPage([item(clock, body="Неоднозначное синтетическое письмо о проекте.")], {})]
    client.post("/workspace/mail/sync", headers=AUTH)
    client.app.state.service.recover_sources(OWNER)
    review = client.get("/workspace/inbox", headers=AUTH).json()["mail_reviews"][0]
    assert review["evidence"]["excerpt"]
    response = client.post(f"/workspace/mail/reviews/{review['id']}/propose", headers=AUTH,
                           json={"title": "Проверить учебный проект"})
    assert response.status_code == 200, response.text
    with factory() as s:
        assert s.scalar(select(Proposal)).status == "pending"
        assert s.scalar(select(Task)) is None
    assert client.post(f"/workspace/mail/reviews/{review['id']}/propose", headers=AUTH,
                       json={"title": "Дубль"}).status_code == 409


def test_old_review_is_not_hidden_by_newer_irrelevant_mail(web, factory, clock):
    from datetime import timedelta
    client, provider = web
    provider.pages = [MailPage([item(clock, body="Несколько неоднозначных вариантов проекта.")], {})]
    client.post("/workspace/mail/sync", headers=AUTH); client.app.state.service.recover_sources(OWNER)
    clock.now += timedelta(seconds=10)
    for batch in range(5):
        provider.pages.append(MailPage([item(clock, f"irrelevant-{batch}-{n}", body="Спасибо за письмо.") for n in range(25)], {"p": batch}))
        client.post("/workspace/mail/sync", headers=AUTH)
        client.app.state.service.recover_sources(OWNER, limit=100)
    assert len(client.get("/workspace/inbox", headers=AUTH).json()["mail_reviews"]) == 1


def test_dismiss_review_does_not_create_or_delete_any_task(web, factory, clock):
    client, provider = web
    provider.pages = [MailPage([item(clock, body="Несколько вариантов учебного проекта.")], {})]
    client.post("/workspace/mail/sync", headers=AUTH); client.app.state.service.recover_sources(OWNER)
    identity = client.get("/workspace/inbox", headers=AUTH).json()["mail_reviews"][0]["id"]
    assert client.post(f"/workspace/mail/reviews/{identity}/dismiss", headers=AUTH).json()["status"] == "ignored"
    assert client.get("/workspace/inbox", headers=AUTH).json()["mail_reviews"] == []
    assert client.post(f"/workspace/mail/reviews/{identity}/dismiss", headers=AUTH).status_code == 409
    with factory() as s:
        assert s.scalar(select(Task)) is None and s.scalar(select(Proposal)) is None
