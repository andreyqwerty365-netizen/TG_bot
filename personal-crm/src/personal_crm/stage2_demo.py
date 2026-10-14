"""Russian synthetic Updates -> real PostgreSQL -> fake worker. No external SDK calls."""
from datetime import UTC, datetime, timedelta
import json
import os
from uuid import uuid4

from sqlalchemy import select

from .adapters import FakeTransport
from .budget import AIError
from .db import sessions
from .integration_config import TelegramConfig
from .models import Dialogue, Job, SourceVersion, Task
from .openai_adapter import ContextInterpreter
from .service import CRMService
from .telegram import TelegramIngress
from .worker import Worker


class OfflineProvider:
    def interpret_context(self, context):
        raise AIError("ai_disabled")


def main():
    factory = sessions(os.environ["CRM_DATABASE_URL"])
    owner = f"stage2-demo-{uuid4().hex}"
    now = [datetime(2026, 10, 13, 8, tzinfo=UTC)]
    clock = lambda: now[0]
    interpreter = ContextInterpreter(OfflineProvider())
    service = CRMService(factory, interpreter, clock)
    service.register(owner, "Europe/Moscow")
    cfg = TelegramConfig(bot_id="303", allowed_user_ids=frozenset({101}), allowed_chat_ids=frozenset({202}))
    def submit(text, ident, reply=None, forward=False):
        message = {"message_id": ident, "date": int(clock().timestamp()), "text": text,
                   "from": {"id": 101, "is_bot": False}, "chat": {"id": 202, "type": "private"}}
        if reply:
            message["reply_to_message"] = {"message_id": reply}
        if forward:
            message["forward_origin"] = {"type": "hidden_user", "date": int((clock() - timedelta(days=3)).timestamp())}
        return TelegramIngress(service, cfg, owner).accept({"update_id": ident, "message": message})
    created = submit("Завтра в 19:00 напомни обновить резюме", 1)
    assert created["status"] == "created"
    assert submit("Завтра в 19:00 напомни обновить резюме", 1)["status"] == "duplicate"
    assert submit("Надо добавить игровой клуб в портфолио", 2)["task"]["deadline"] is None
    assert submit("Я пришлю тебе договор", 3, forward=True)["task"]["kind"] == "waiting"
    asked = submit("Перенеси последнее напоминание на 23 числа", 4)
    assert asked["status"] == "clarification"
    # A new service and engine/session factory read the same durable question.
    service = CRMService(sessions(os.environ["CRM_DATABASE_URL"]), interpreter, clock)
    assert submit("в субботу", 5, reply=4)["status"] == "changed"
    with factory() as s:
        assert s.scalar(select(Dialogue).where(Dialogue.source_version_id == asked["source_version_id"])).status == "resolved"
        exact = s.scalar(select(Job).where(Job.owner_id == owner, Job.kind == "exact", Job.status == "pending"))
        assert exact.run_at == datetime(2026, 10, 17, 16, tzinfo=UTC)
        assert s.get(SourceVersion, created["source_version_id"]).status == "processed"
    assert submit("Что на сегодня?", 6)["status"] == "overview"
    fake = FakeTransport()
    worker = Worker(factory, fake, clock, owner_id=owner)
    replies = 0
    while worker.tick() == "sent":
        replies += 1
    assert replies == 6
    now[0] = datetime(2026, 10, 17, 16, tzinfo=UTC)
    assert worker.tick() == "sent"
    assert submit("Резюме обновил", 7)["task"]["state"] == "done"
    assert worker.tick() == "sent"  # committed completion acknowledgement
    with factory() as s:
        assert s.get(Task, created["task"]["id"]).state == "done"
        assert s.scalar(select(Job).where(Job.owner_id == owner, Job.kind == "repeat")).status == "cancelled"
    print(json.dumps({"synthetic_updates": True, "direct_exact_reminder": True, "duplicate_applied_once": True,
        "dialogue_survived_new_service": True, "fake_replies": replies + 1, "fake_exact_delivery": 1,
        "completion_cancelled_repeat": True, "real_external_calls": 0}))


if __name__ == "__main__":
    main()
