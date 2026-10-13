"""Exercise a running local fake API/worker. Credentials are read only from environment."""
from datetime import UTC, datetime, timedelta
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from personal_crm.db import sessions
from personal_crm.models import Attempt, Job

base = os.getenv("CRM_API_BASE", "http://127.0.0.1:8001")
token = os.environ["CRM_OWNER_TOKEN"]
owner = os.environ["CRM_OWNER_ID"]
factory = sessions(os.environ["CRM_DATABASE_URL"])


def call(path, body=None, authenticate=True):
    headers = {"Content-Type": "application/json"}
    if authenticate:
        headers["Authorization"] = "Bearer " + token
    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urlopen(request, timeout=5) as response:
        return json.load(response)


for attempt in range(30):
    try:
        assert call("/ready", authenticate=False)["status"] == "ready"
        break
    except (URLError, HTTPError, OSError):
        time.sleep(1)
else:
    raise RuntimeError("API did not become ready")

try:
    call("/tasks", authenticate=False)
    raise AssertionError("Unauthenticated access was allowed")
except HTTPError as error:
    assert error.code == 401

created = call("/sources", {"external_id": f"smoke-{uuid4()}", "account": "synthetic-http",
                           "text": "Подготовить синтетический отчёт"})
assert created["status"] == "created"
task_id = created["task"]["id"]
call(f"/tasks/{task_id}/commands", {"version": 1, "action": "reminder",
                                   "at": (datetime.now(UTC) + timedelta(seconds=2)).isoformat()})
from personal_crm.models import Reminder
for attempt in range(15):
    with factory() as s:
        delivery = s.scalar(select(Attempt).join(Job).join(Reminder).where(
            Reminder.task_id == task_id, Attempt.outcome == "success"))
        if delivery:
            assert delivery.provider_id.startswith("fake:")
            break
    time.sleep(1)
else:
    raise AssertionError("Background worker did not record a fake delivery")

call(f"/tasks/{task_id}/commands", {"version": 2, "action": "close"})
with factory() as s:
    repeat = s.scalar(select(Job).join(Reminder).where(Reminder.task_id == task_id, Job.kind == "repeat"))
    assert repeat.status == "cancelled"
planned = call("/sources", {"external_id": f"smoke-plan-{uuid4()}", "account": "synthetic-http",
                            "text": "Подготовить синтетический отчёт"})["task"]
today = datetime.now(ZoneInfo(os.environ["CRM_TIMEZONE"])).date()
for offset in range(1, 5):
    planned = call(f"/tasks/{planned['id']}/commands", {"version": planned["version"], "action": "plan",
                  "planned_on": (today + timedelta(days=offset)).isoformat()})
assert planned["plan_postponements"] == 3 and planned["deadline"] is None
assert any(g["task_id"] == planned["id"] and g["kind"] == "obstacle" for g in call("/guidance"))
assert len(call(f"/tasks/{planned['id']}/history")) == 5
assert "main" in call("/overview")
call(f"/tasks/{planned['id']}/commands", {"version": planned["version"], "action": "close"})
print("HTTP smoke passed: readiness, owner auth, source, reminder, background fake delivery, close/cancel, plan, overview, history")
