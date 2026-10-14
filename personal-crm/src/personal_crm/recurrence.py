"""Explicit owner-authorized calendar rules; one outstanding occurrence per rule."""
from calendar import monthrange
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .language import AmbiguousDate, local_instant
from .models import Recurrence, RecurrenceHistory, Reminder, SourceVersion, Task
from .schema import Incoming, Interpretation
from .service import CRMError, snapshot


def next_day(rule, after):
    anchor, interval = rule.anchor_on, rule.interval
    try:
        if rule.frequency in ("daily", "weekly"):
            days = interval * (7 if rule.frequency == "weekly" else 1)
            return anchor + timedelta(days=max(0, (after - anchor).days // days + 1) * days)
        months = max(0, ((after.year - anchor.year) * 12 + after.month - anchor.month) // interval)
        while True:
            year, month0 = divmod(anchor.year * 12 + anchor.month - 1 + months * interval, 12)
            day = date(year, month0 + 1, min(anchor.day, monthrange(year, month0 + 1)[1]))
            if day > after:
                return day
            months += 1
    except (ValueError, OverflowError):
        raise CRMError("recurrence_out_of_range", 422) from None


def rule_view(rule):
    return {"id": rule.id, "version": rule.version, "status": rule.status, "frequency": rule.frequency,
            "interval": rule.interval, "anchor_on": rule.anchor_on.isoformat(), "timezone": rule.timezone,
            "reminder_time": rule.reminder_time, "template": rule.template}


def record_rule(s, rule, before, now):
    s.add(RecurrenceHistory(owner_id=rule.owner_id, recurrence_id=rule.id, version=rule.version,
                            before=before, after=rule_view(rule), created_at=now))


def set_reminder(s, service, task, rule):
    if not rule.reminder_time:
        return
    try:
        at = local_instant(task.occurrence_on, time.fromisoformat(rule.reminder_time), rule.timezone)
    except AmbiguousDate:
        task.recurrence_warning = "ambiguous_or_invalid_time"
        return
    if at <= service.clock():
        task.recurrence_warning = "recurrence_reminder_missed"
        return
    service._schedule(s, task, at)


def attach(s, service, profile, task, body):
    if task.state in ("done", "cancelled") or task.kind == "note":
        raise CRMError("task_inactive", 422)
    if task.recurrence_id:
        raise CRMError("recurrence_already_exists")
    if not profile.timezone:
        raise CRMError("profile_timezone_required", 422)
    rule = Recurrence(owner_id=profile.id, frequency=body.frequency, interval=body.interval,
        anchor_on=body.anchor_on, reminder_time=body.reminder_time, timezone=profile.timezone,
        template={"title": task.title, "kind": task.kind, "project_id": task.project_id, "draft_steps": task.draft_steps})
    next_day(rule, body.anchor_on)  # Reject schedules beyond the representable calendar before saving anything.
    s.add(rule); s.flush()
    before = snapshot(task)
    task.recurrence_id, task.occurrence_on, task.occurrence_timezone = rule.id, body.anchor_on, rule.timezone
    task.planned_on, task.version = body.anchor_on, task.version + 1
    existing = s.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True)))
    if existing:
        existing.task_version = task.version
    else:
        set_reminder(s, service, task, rule)
    service._history(s, task, before, "owner", "recurrence_created", rule.id)
    record_rule(s, rule, None, service.clock())
    return rule


def advance(s, service, previous):
    if not previous.recurrence_id:
        return None
    rule = s.scalar(select(Recurrence).where(Recurrence.id == previous.recurrence_id,
                    Recurrence.owner_id == previous.owner_id).with_for_update())
    if not rule or rule.status != "active":
        return None
    today = service.clock().astimezone(ZoneInfo(rule.timezone)).date()
    day = next_day(rule, max(previous.occurrence_on, today))
    s.flush()  # The completed occurrence must leave the partial unique index before insertion.
    incoming = Incoming(account="recurrence", external_id=f"{rule.id}:{day.isoformat()}",
                        text=rule.template["title"])
    identity = service._ingest(s, previous.owner_id, "owner", incoming,
        {"recurrence_id": rule.id, "rule_version": rule.version, "occurrence_on": day.isoformat()})
    version = s.get(SourceVersion, identity)
    if version.status == "processed":
        return s.scalar(select(Task).where(Task.source_version_id == identity))
    output = Interpretation(source_version_id=identity, operation="create", title=rule.template["title"],
                            kind=rule.template["kind"], planned_on=day, draft_steps=rule.template.get("draft_steps", []))
    task = service._create(s, previous.owner_id, identity, output, "recurrence_occurrence", rule.id,
                           project_id=rule.template.get("project_id"), recurrence=rule, occurrence_on=day)
    set_reminder(s, service, task, rule)
    # _create records initial history; include its explicitly requested recurring reminder/warning.
    from .models import History
    history = s.scalar(select(History).where(History.task_id == task.id))
    at = s.scalar(select(Reminder.at).where(Reminder.task_id == task.id))
    history.after = {**snapshot(task), "reminder_at": at.isoformat() if at else None}
    version.status, version.result = "processed", {"status": "created", "task": snapshot(task)}
    return task
