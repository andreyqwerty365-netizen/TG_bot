"""Synthetic mailbox laboratory. Refuses every non-test database and real owner."""
from datetime import UTC, datetime
import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import select

from .adapters import FixtureInterpreter
from .config import Settings
from .db import sessions
from .mail import MailItem, MailPage, MailSync
from .models import Proposal, Task
from .service import CRMService


def guard(settings):
    if settings.environment == 'production':
        raise RuntimeError('Synthetic mail is forbidden in production')
    if not settings.database_url.rsplit("/", 1)[-1].startswith("personal_crm_test") or not settings.owner_id.startswith("synthetic-"):
        raise RuntimeError("Synthetic mail requires personal_crm_test* database and synthetic-* owner")
    if settings.mail.enabled or settings.mail.consent:
        raise RuntimeError("Disable both real mail flags before using the synthetic laboratory")


class SyntheticMailbox:
    name = "synthetic"
    account_key = "synthetic-laboratory"

    def changes(self, cursor, since, limit, tracked):
        sequence = int((cursor or {}).get("sequence", 0)) + 1
        now = datetime.now(UTC)
        items = [MailItem(key=f"demo-{sequence}", message_id=f"<demo-{sequence}@example.invalid>", references=(),
                         folder="inbox", original_at=now, arrived_at=now, subject=f"Почтовая проверка {sequence}",
                         sender="Учебный отправитель <sender@example.invalid>",
                         text="Пожалуйста, проверьте учебный отчёт. Это синтетическое письмо.", attachments=True),
                 MailItem(key=f"promise-{sequence}", message_id=f"<promise-{sequence}@example.invalid>", references=(),
                          folder="sent", original_at=now, arrived_at=now, subject=f"Учебное обещание {sequence}",
                          sender="Учебный владелец <owner@example.invalid>", text="Я пришлю учебный документ."),
                 MailItem(key=f"review-{sequence}", message_id=f"<review-{sequence}@example.invalid>", references=(),
                          folder="inbox", original_at=now, arrived_at=now, subject=f"Письмо для просмотра {sequence}",
                          sender="Учебный отправитель <sender@example.invalid>", text="Обсудили несколько вариантов проекта. Нужна оценка контекста.")]
        return MailPage(items[:limit], {"sequence": sequence})


def create_demo_app():
    from .api import create_app
    settings = Settings.from_env()
    guard(settings)
    return create_app(settings, mail_provider=SyntheticMailbox())


def main():
    settings = Settings.from_env()
    # Standalone demo uses a fresh synthetic owner; never writes in the configured real profile.
    from dataclasses import replace
    settings = replace(settings, owner_id="synthetic-mail-demo-" + uuid4().hex, owner_token="synthetic-demo-only")
    guard(settings)
    factory = sessions(settings.database_url)
    service = CRMService(factory, FixtureInterpreter())
    service.register(settings.owner_id, "Europe/Moscow")
    result = MailSync(service, SyntheticMailbox()).run(settings.owner_id)
    assert result["saved"] == 3
    with factory() as s:
        assert not s.scalar(select(Task).where(Task.owner_id == settings.owner_id))
        assert not s.scalar(select(Proposal).where(Proposal.owner_id == settings.owner_id))
    # A separate process resumes the committed sources without mailbox access.
    subprocess.run([sys.executable, "-m", "personal_crm.source_worker", "--once"], check=True,
                   env={**os.environ, "CRM_OWNER_ID": settings.owner_id, "CRM_OWNER_TOKEN": settings.owner_token,
                        "CRM_DATABASE_URL": settings.database_url, "CRM_OPENAI_ENABLED": "false",
                        "CRM_MAIL_ENABLED": "false", "CRM_MAIL_READ_CONSENT": "false"})
    with factory() as s:
        proposals = s.scalars(select(Proposal).where(Proposal.owner_id == settings.owner_id)).all()
        assert len(proposals) == 2
        assert not s.scalar(select(Task).where(Task.owner_id == settings.owner_id))
        identity, version = proposals[0].id, proposals[0].version
    assert service.confirm(settings.owner_id, identity, version)["status"] == "accepted"
    with factory() as s:
        assert len(s.scalars(select(Task).where(Task.owner_id == settings.owner_id)).all()) == 1
    print("mail demo: saved=3 proposals=2 tasks_before_confirmation=0 tasks_after_confirmation=1 real_external_calls=0")


if __name__ == "__main__":
    main()
