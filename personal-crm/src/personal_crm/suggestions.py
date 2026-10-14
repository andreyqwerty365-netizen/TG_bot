"""Local, inspectable planning proposals. Generation never changes tasks or schedules."""
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
from zoneinfo import ZoneInfo

from fastapi import Depends
from pydantic import Field
from sqlalchemy import select

from .models import History, PlanningSuggestion, Task
from .planning_config import PlanningPolicy
from .schema import Strict
from .service import CRMError, CommandValues


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def fresh(s, item, profile, now):
    from .accompaniment import task_visible
    if item.profile_version is not None:
        expires = item.payload.get("valid_until")
        return item.profile_version == profile.version and profile.preferred_reminder_time is None and (
            datetime.fromisoformat(expires) >= now if expires else item.created_at >= now - timedelta(days=14))
    task = s.get(Task, item.task_id)
    if not task or task.owner_id != profile.id or task.version != item.task_version or task.state != "active" or not task_visible(task, profile, now):
        return False
    if item.kind == "early":
        return bool(profile.timezone and date.fromisoformat(item.payload["planned_on"]) >= now.astimezone(ZoneInfo(profile.timezone)).date())
    return True


def view(item):
    return {"id": item.id, "version": item.version, "kind": item.kind, "task_id": item.task_id,
            "task_version": item.task_version, "payload": item.payload}


def pending(s, profile, now):
    items = [view(item) for item in s.scalars(select(PlanningSuggestion).where(PlanningSuggestion.owner_id == profile.id,
        PlanningSuggestion.status == "pending").order_by(PlanningSuggestion.created_at, PlanningSuggestion.id)) if fresh(s, item, profile, now)]
    return sorted(items, key=lambda item: ({"early": 0, "reminder_time": 1, "step": 2}[item["kind"]],
                                           item["payload"].get("planned_on", ""), item["id"]))


def offer(s, profile, kind, event_key, payload, now, task=None):
    item = s.scalar(select(PlanningSuggestion).where(PlanningSuggestion.owner_id == profile.id,
                    PlanningSuggestion.event_key == event_key))
    if item and item.status in ("accepted", "dismissed"):
        return
    if not item:
        item = PlanningSuggestion(owner_id=profile.id, event_key=event_key, kind=kind, created_at=now,
            task_id=task.id if task else None, payload=payload)
        s.add(item)
    elif item.task_version != (task.version if task else None) or item.profile_version != (None if task else profile.version):
        item.version += 1
    item.task_version, item.profile_version = (task.version, None) if task else (None, profile.version)
    item.status, item.payload = "pending", payload


def refresh(s, profile, now, policy=PlanningPolicy()):
    from .accompaniment import deadline_identity, task_visible
    for item in s.scalars(select(PlanningSuggestion).where(PlanningSuggestion.owner_id == profile.id, PlanningSuggestion.status == "pending")):
        if not fresh(s, item, profile, now):
            item.status = "stale"
    tasks = s.scalars(select(Task).where(Task.owner_id == profile.id, Task.kind == "task", Task.state == "active")
                      .order_by(Task.focused.desc(), Task.created_at, Task.id).limit(policy.task_limit)).all()
    for task in tasks:
        if not task_visible(task, profile, now):
            continue
        step = task.draft_steps[0] if task.draft_steps else f"Откройте материалы по делу «{task.title[:200]}» и запишите один конкретный следующий шаг."
        offer(s, profile, "step", f"step:{task.id}:{key(task.draft_steps)}",
              {"title": task.title, "step": step, "generic": not bool(task.draft_steps)}, now, task)
        if task.deadline and profile.timezone and task.planned_on is None:
            today = now.astimezone(ZoneInfo(profile.timezone)).date()
            due = date.fromisoformat(task.deadline["value"]) if task.deadline["precision"] == "date" else datetime.fromisoformat(task.deadline["value"]).astimezone(ZoneInfo(profile.timezone)).date()
            if 1 <= (due - today).days <= policy.early_horizon_days:
                proposed = max(today, due - timedelta(days=policy.early_lead_days))
                offer(s, profile, "early", f"early:{task.id}:{deadline_identity(task.deadline)}",
                    {"title": task.title, "planned_on": proposed.isoformat(), "deadline": task.deadline,
                     "timezone": profile.timezone}, now, task)
    if not profile.preferred_reminder_time and profile.timezone:
        latest = {}
        seen = set()
        rows = s.scalars(select(History).where(History.owner_id == profile.id, History.actor == "owner",
            History.created_at >= now - timedelta(days=policy.history_days), History.reason.in_(["explicit_command", "explicit_web_edit", "explicit_web_create"]))
            .order_by(History.created_at.desc(), History.task_version.desc(), History.id).limit(100))
        for row in rows:
            at = row.after.get("reminder_at")
            before = row.before or {}
            # Retained reminders in title/project/close history are not choices of a time.
            if row.task_id in seen or (row.reason != "explicit_web_create" and
                (before.get("state") != row.after.get("state") or before.get("reminder_at") == at)):
                continue
            seen.add(row.task_id)
            if at:
                wall = datetime.fromisoformat(at).astimezone(ZoneInfo(profile.timezone)).strftime("%H:%M")
                latest[row.task_id] = (wall, row.id)
        counts = Counter(value[0] for value in latest.values())
        if counts:
            wall, count = counts.most_common(1)[0]
            if count >= policy.required_choices:
                evidence = sorted(row_id for value, row_id in latest.values() if value == wall)
                offer(s, profile, "reminder_time", f"reminder-time:{wall}:{key(evidence)}",
                    {"reminder_time": wall, "timezone": profile.timezone, "explicit_choices": count,
                     "valid_until": (now + timedelta(days=policy.history_days)).isoformat()}, now)
    s.flush()
    return {"items": pending(s, profile, now)}


class Decision(Strict):
    version: int = Field(gt=0)
    accept: bool = True


def install_suggestions(app, service, actor, policy=PlanningPolicy()):
    factory = service.factory

    @app.get("/workspace/suggestions")
    def list_suggestions(owner=Depends(actor)):
        with factory() as s:
            from .models import Profile
            return {"items": pending(s, s.get(Profile, owner), service.clock())}

    @app.post("/workspace/suggestions/refresh")
    def generate(owner=Depends(actor)):
        with factory.begin() as s:
            profile = service.owner(s, owner)
            return refresh(s, profile, service.clock(), policy)

    @app.post("/workspace/suggestions/{identity}/confirm")
    def confirm(identity: str, body: Decision, owner=Depends(actor)):
        conflict = False
        with factory.begin() as s:
            profile = service.owner(s, owner)
            item = s.scalar(select(PlanningSuggestion).where(PlanningSuggestion.id == identity,
                PlanningSuggestion.owner_id == owner).with_for_update())
            if not item:
                raise CRMError("not_found", 404)
            if item.version != body.version or item.status != "pending":
                raise CRMError("proposal_conflict")
            if not body.accept:
                item.status = "dismissed"
            elif not fresh(s, item, profile, service.clock()):
                item.status, conflict = "stale", True
            elif item.kind == "reminder_time":
                profile.preferred_reminder_time = item.payload["reminder_time"]
                profile.version += 1
                item.status = "accepted"
            else:
                task = service.task(s, owner, item.task_id, item.task_version)
                values = CommandValues(planned_on=date.fromisoformat(item.payload["planned_on"])) if item.kind == "early" else CommandValues()
                service._change(s, task, "plan" if item.kind == "early" else "start", values,
                                "planning_confirmation", item.id)
                item.status = "accepted"
            item.version += 1
            result = {"status": item.status}
        if conflict:
            raise CRMError("version_conflict")
        return result
