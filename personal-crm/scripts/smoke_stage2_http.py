"""Running Uvicorn/worker + PostgreSQL, synthetic Updates only, adapters disabled."""
from datetime import UTC, datetime, timedelta
import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from personal_crm.db import sessions
from personal_crm.models import Attempt, Job, OutgoingReply, Reminder


base = os.getenv("CRM_API_BASE", "http://127.0.0.1:8001")
factory = sessions(os.environ["CRM_DATABASE_URL"])
token = os.environ["CRM_OWNER_TOKEN"]


def call(path, body=None):
    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


ident = int(uuid4().hex[:8], 16) >> 2


def update(text, offset=0, reply=False, user=101):
    message = {"message_id": ident + offset, "date": int(time.time()), "text": text,
               "from": {"id": user, "is_bot": False}, "chat": {"id": 202, "type": "private"}}
    if reply:
        message["reply_to_message"] = {"message_id": ident}
    return {"update_id": ident + offset, "message": message}


try:
    call("/telegram/webhook", update("Надо обновить резюме"))
    raise AssertionError("Live webhook unexpectedly enabled")
except HTTPError as error:
    assert error.code == 404
try:
    call("/adapters/synthetic-telegram", update("Надо обновить резюме", user=999))
    raise AssertionError("Unauthorized actor accepted")
except HTTPError as error:
    assert error.code == 403

payload = update("Завтра в 19:00 напомни обновить резюме")
created = call("/adapters/synthetic-telegram", payload)
assert created["status"] == "created" and created["task"]["deadline"] is None
task = created["task"]
with factory() as s:
    at = s.scalar(select(Reminder.at).where(Reminder.task_id == task["id"], Reminder.active.is_(True)))
    zone = ZoneInfo(os.environ["CRM_TIMEZONE"])
    tomorrow = datetime.now(zone).date() + timedelta(days=1)
    assert at.astimezone(zone).date() == tomorrow and at.astimezone(zone).hour == 19
assert call("/adapters/synthetic-telegram", payload)["status"] == "duplicate"
assert call("/adapters/synthetic-telegram", update("Неизвестная синтетическая формулировка", 1))["code"] == "ai_disabled"
call(f"/tasks/{task['id']}/commands", {"version": task["version"], "action": "reminder",
    "at": (datetime.now(UTC) + timedelta(seconds=2)).isoformat()})
for _ in range(15):
    with factory() as s:
        reply = s.scalar(select(Attempt).join(Job).join(OutgoingReply).where(
            OutgoingReply.source_version_id == created["source_version_id"], Attempt.outcome == "success"))
        exact = s.scalar(select(Attempt).join(Job).join(Reminder).where(
            Reminder.task_id == task["id"], Attempt.kind == "exact", Attempt.outcome == "success"))
        if reply and exact:
            assert reply.provider_id.startswith("fake:") and exact.provider_id.startswith("fake:")
            break
    time.sleep(1)
else:
    raise AssertionError("Queued reply/exact not delivered by fake worker")
done = call("/adapters/synthetic-telegram", update("Резюме обновил", 2, reply=True))
assert done["status"] == "changed" and done["task"]["state"] == "done"
with factory() as s:
    repeat = s.scalar(select(Job).join(Reminder).where(Reminder.task_id == task["id"], Job.kind == "repeat"))
    assert repeat.status == "cancelled"
print("Stage 2 HTTP smoke passed: disabled webhook, actor auth, Russian Update, exact local time, dedupe, disabled AI, queued fake reply/exact, source-bound completion, repeat cancellation")
