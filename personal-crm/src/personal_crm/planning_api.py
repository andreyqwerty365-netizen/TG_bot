"""Owner controls for recurring work and confirmation of a complete step plan."""
from datetime import date, time
import json
from typing import Literal

from fastapi import Depends
from pydantic import Field, field_validator
from sqlalchemy import select, update

from .models import Recurrence, Reminder, SourceVersion, Task, uid
from .recurrence import attach, next_day, record_rule, rule_view
from .schema import Incoming, Interpretation, Strict
from .service import CRMError, snapshot


def valid_time(value):
    if value is not None:
        parsed = time.fromisoformat(value)
        if len(value) != 5 or parsed.tzinfo or parsed.second or parsed.microsecond:
            raise ValueError("Use HH:MM")
    return value


class RecurrenceCreate(Strict):
    version: int = Field(gt=0)
    frequency: Literal["daily", "weekly", "monthly"]
    interval: int = Field(ge=1, le=365)
    anchor_on: date
    reminder_time: str | None = None
    _time = field_validator("reminder_time")(valid_time)


class RecurrenceEdit(Strict):
    version: int = Field(gt=0)
    status: Literal["active", "stopped"] | None = None
    frequency: Literal["daily", "weekly", "monthly"] | None = None
    interval: int | None = Field(default=None, ge=1, le=365)
    reminder_time: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=2000)
    _time = field_validator("reminder_time")(valid_time)


class Steps(Strict):
    version: int = Field(gt=0)
    steps: list[str] = Field(max_length=12)

    @field_validator("steps")
    @classmethod
    def valid_steps(cls, values):
        values = [value.strip() for value in values]
        if any(not value or len(value) > 500 for value in values) or len(set(values)) != len(values):
            raise ValueError("Use distinct non-empty steps up to 500 characters")
        return values


class PlanConfirmation(Strict):
    version: int = Field(gt=0)
    request_id: str = Field(min_length=1, max_length=128)


def current_view(s, task):
    at = s.scalar(select(Reminder.at).where(Reminder.task_id == task.id, Reminder.active.is_(True)))
    return {**snapshot(task), "reminder_at": at.isoformat() if at else None}


def install_planning(app, service, actor):
    factory = service.factory

    @app.post("/workspace/tasks/{identity}/recurrence")
    def create_recurrence(identity: str, body: RecurrenceCreate, owner=Depends(actor)):
        with factory.begin() as s:
            profile = service.owner(s, owner)
            task = service.task(s, owner, identity, body.version)
            rule = attach(s, service, profile, task, body)
            return {"task": current_view(s, task), "rule": rule_view(rule)}

    @app.patch("/workspace/recurrences/{identity}")
    def edit_recurrence(identity: str, body: RecurrenceEdit, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            rule = s.scalar(select(Recurrence).where(Recurrence.id == identity, Recurrence.owner_id == owner).with_for_update())
            if not rule:
                raise CRMError("not_found", 404)
            if rule.version != body.version:
                raise CRMError("version_conflict")
            fields = body.model_fields_set - {"version"}
            if not fields:
                raise CRMError("empty_edit", 422)
            before = rule_view(rule)
            for field in fields:
                value = getattr(body, field)
                if value is None and field != "reminder_time":
                    raise CRMError("setting_value_required", 422)
                if field == "title":
                    if not value.strip():
                        raise CRMError("title_required", 422)
                    rule.template = {**rule.template, "title": value.strip()}
                else:
                    setattr(rule, field, value)
            if body.status == "active" and not s.scalar(select(Task.id).where(Task.recurrence_id == rule.id,
                    Task.owner_id == owner, Task.state.in_(["active", "in_progress", "deferred"]))):
                raise CRMError("recurrence_has_no_open_task")
            next_day(rule, rule.anchor_on)
            rule.version += 1
            record_rule(s, rule, before, service.clock())
            return rule_view(rule)

    @app.put("/workspace/tasks/{identity}/steps")
    def steps_edit(identity: str, body: Steps, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            task = service.task(s, owner, identity, body.version)
            if task.state in ("done", "cancelled"):
                raise CRMError("task_inactive", 422)
            if task.draft_steps != body.steps:
                before = snapshot(task)
                task.draft_steps, task.steps_revision, task.version = body.steps, task.steps_revision + 1, task.version + 1
                service._history(s, task, before, "owner", "explicit_step_draft", uid())
                s.execute(update(Reminder).where(Reminder.task_id == task.id,
                    Reminder.active.is_(True)).values(task_version=task.version))
            return current_view(s, task)

    @app.post("/workspace/tasks/{identity}/steps/confirm")
    def confirm_plan(identity: str, body: PlanConfirmation, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            task = service.task(s, owner, identity)
            request_text = json.dumps({"task_id": identity, "version": body.version}, sort_keys=True)
            receipt_id = service._ingest(s, owner, "owner", Incoming(account="step-confirmation",
                external_id=body.request_id, text=request_text))
            receipt = s.get(SourceVersion, receipt_id)
            if receipt.status == "processed":
                return receipt.result
            if task.version != body.version:
                raise CRMError("version_conflict")
            if task.state in ("done", "cancelled") or not task.draft_steps:
                raise CRMError("step_plan_required", 422)
            children = s.scalars(select(Task).where(Task.parent_task_id == identity, Task.owner_id == owner,
                Task.step_batch == task.steps_revision).order_by(Task.step_index)).all()
            if task.promoted_steps_revision != task.steps_revision:
                before = snapshot(task)
                for index, title in enumerate(task.draft_steps):
                    version_id = service._ingest(s, owner, "owner", Incoming(account="confirmed-steps",
                        external_id=f"{identity}:{task.steps_revision}:{index}", text=title),
                        {"parent_task_id": identity, "steps_revision": task.steps_revision})
                    source = s.get(SourceVersion, version_id)
                    output = Interpretation(source_version_id=version_id, operation="create", title=title)
                    child = service._create(s, owner, version_id, output, "confirmation", receipt_id,
                        project_id=task.project_id, parent_task=task, step_index=index)
                    source.status, source.result = "processed", {"status": "created", "task": snapshot(child)}
                    children.append(child)
                task.promoted_steps_revision, task.version = task.steps_revision, task.version + 1
                service._history(s, task, before, "owner", "step_plan_confirmed", receipt_id)
                for reminder in s.scalars(select(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True))):
                    reminder.task_version = task.version
            result = {"status": "created", "parent": snapshot(task), "children": [snapshot(t) for t in children]}
            receipt.status, receipt.result = "processed", result
            return result
