"""Twenty-eight synthetic days on real PostgreSQL, with controlled clocks and fake delivery."""
from collections import Counter
from datetime import UTC, date, datetime, timedelta
import json
import os
from uuid import uuid4

from sqlalchemy import select

from .adapters import FakeTransport, FixtureInterpreter
from .db import sessions
from .models import Attempt, Guidance, Job, Task
from .schema import Deadline, Incoming
from .service import CRMService
from .worker import Worker


def main():
    factory = sessions(os.environ["CRM_DATABASE_URL"])
    owner = "simulation-" + uuid4().hex
    now = [datetime(2026, 10, 13, 8, tzinfo=UTC)]
    clock = lambda: now[0]
    fixtures = {f"Synthetic obligation {i}": dict(operation="create", title=f"Synthetic obligation {i}", obvious=True)
                for i in range(14)}
    service = CRMService(factory, FixtureInterpreter(fixtures), clock)
    service.register(owner, "Europe/Berlin")  # an explicit test timezone, never a real user's inferred zone
    tasks = []
    for i in range(14):
        source = service.ingest(owner, "owner", Incoming(external_id=str(i), account="synthetic-simulation",
                                                        text=f"Synthetic obligation {i}"))
        tasks.append(service.process(owner, source)["task"])
    task = tasks[8]
    service.command(owner, task["id"], 1, "deadline", deadline=Deadline(
        precision="date", value="2026-10-15", original="synthetic October 15", timezone="Europe/Berlin"))
    planned = tasks[9]
    for day in (13, 14, 15, 16):
        planned = service.command(owner, planned["id"], planned["version"], "plan", planned_on=date(2026, 10, day))
    for task in tasks[10:13]:
        service.command(owner, task["id"], 1, "reminder", at=clock() - timedelta(days=3))
    undated_ids = {task["id"] for i, task in enumerate(tasks) if i != 8}
    transport = FakeTransport()
    for day in range(28):
        now[0] = datetime(2026, 10, 13, 12, tzinfo=UTC) + timedelta(days=day)
        worker = Worker(factory, transport, clock, owner_id=owner)
        for _ in range(8):
            if worker.tick(digest=True) == "idle":
                break
        else:
            raise AssertionError("Synthetic day did not settle")
    with factory() as s:
        attempts = s.scalars(select(Attempt).where(Attempt.owner_id == owner)).all()
        digests = [a for a in attempts if a.kind == "digest" and a.outcome == "success"]
        assert len(digests) == 28 and len({a.local_day for a in digests}) == 28
        seen = {identity for a in digests for identity in a.payload.get("forgotten_ids", [])}
        assert seen == undated_ids
        initiatives = [a for a in attempts if a.kind in ("initiative", "repeat") and a.outcome == "success"]
        assert all(count <= 2 for count in Counter(a.local_day for a in initiatives).values())
        starts = sorted(a.started_at for a in initiatives)
        assert all(right - left >= timedelta(hours=4) for left, right in zip(starts, starts[1:]))
        guides = s.scalars(select(Guidance).where(Guidance.owner_id == owner)).all()
        assert Counter(g.kind for g in guides) == {"obstacle": 1, "overdue": 1, "missed": 1}
        assert all(g.status == "sent" for g in guides)
        missed = s.scalars(select(Job).where(Job.owner_id == owner, Job.cancel_reason == "missed_after_outage")).all()
        assert len(missed) == 3
        persisted = s.scalars(select(Task).where(Task.owner_id == owner)).all()
        assert len(persisted) == 14 and all(t.state == "active" for t in persisted)
    print(json.dumps({"simulated_days": 28, "daily_digests": len(digests), "forgotten_tasks_presented": len(seen),
        "overdue_announcements": 1, "obstacle_questions": 1, "missed_jobs_consolidated": len(missed),
        "automatic_completions": 0, "real_external_calls": 0}))


if __name__ == "__main__":
    main()
