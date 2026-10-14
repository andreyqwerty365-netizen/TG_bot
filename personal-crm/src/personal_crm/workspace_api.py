"""Owner-authorized web actions over the same tasks, history and reminder queue."""
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, Query
from fastapi.responses import RedirectResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, field_validator
from sqlalchemy import Date, DateTime, case, cast, func, select

from .budget import AIError, BudgetLedger, micro_usd
from .language import AmbiguousDate, local_instant
from .models import Dialogue, History, Job, Profile, Project, Proposal, Reminder, Source, SourceVersion, Task, uid
from .schema import Deadline, Incoming, Interpretation, Strict
from .service import CRMError, CommandValues, snapshot


class ManualTask(Strict):
    request_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=2000)
    kind: Literal["task", "waiting", "note"] = "task"
    reminder_local: str | None = None
    deadline: Deadline | None = None
    deadline_local: str | None = None
    planned_on: date | None = None
    project_id: str | None = None

    @field_validator("title")
    @classmethod
    def meaningful_title(cls, value):
        if not value.strip():
            raise ValueError("Title required")
        return value.strip()


class Capture(Strict):
    request_id: str = Field(min_length=1,max_length=128)
    text: str = Field(min_length=1,max_length=16000)

    @field_validator('text')
    @classmethod
    def meaningful_text(cls,value):
        if not value.strip():
            raise ValueError('Text required')
        return value.strip()


class TaskEdit(Strict):
    version: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=2000)
    reminder_local: str | None = None
    deadline: Deadline | None = None
    deadline_local: str | None = None
    planned_on: date | None = None
    project_id: str | None = None


class ProjectInput(Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError("Name required")
        return value.strip()


class ProjectEdit(ProjectInput):
    version: int = Field(gt=0)


class Preferences(Strict):
    version: int = Field(gt=0)
    timezone: str | None = Field(default=None, max_length=64)
    digest_hour: int | None = Field(default=None, ge=0, le=23)
    initiative_limit: int | None = Field(default=None, ge=0, le=2)
    catchup_grace_seconds: int | None = Field(default=None, ge=60, le=86400)
    ai_paused: bool | None = None
    ai_budget_cap_micro_usd: int | None = Field(default=None, ge=0)
    preferred_reminder_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class Reply(Strict):
    request_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=16000)


def reminder_instant(value, profile):
    if not profile.timezone:
        raise CRMError("profile_timezone_required", 422)
    try:
        wall = datetime.fromisoformat(value)
        if wall.tzinfo is not None:
            raise ValueError()
        return local_instant(wall.date(), wall.time(), profile.timezone)
    except (ValueError, AmbiguousDate):
        raise CRMError("ambiguous_or_invalid_time", 422) from None


def project_for(s, owner, identity):
    if identity is None:
        return None
    project = s.scalar(select(Project).where(Project.id == identity, Project.owner_id == owner))
    if not project:
        raise CRMError("not_found", 404)
    return project


def local_deadline(value, profile):
    if value is None:
        return None
    if not profile.timezone:
        raise CRMError("profile_timezone_required", 422)
    if len(value) == 10:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise CRMError("invalid_date", 422) from None
        return Deadline(precision="date", value=value, original=value, timezone=profile.timezone)
    at = reminder_instant(value, profile)
    return Deadline(precision="instant", value=at.isoformat(), original=value, timezone=profile.timezone)


def task_view(task, reminder=None):
    return {**snapshot(task), "reminder_at": reminder.at.isoformat() if reminder else None,
            "created_at": task.created_at.isoformat()}


def install_workspace(app, service, settings, actor):
    factory = service.factory

    @app.get('/workspace/system')
    def system_status(owner=Depends(actor)):
        from .operations import overview
        from .recovery import BackupConfig
        return overview(factory,owner,now=service.clock(),delivery_enabled=settings.telegram.send_enabled,
                        backup_enabled=BackupConfig.from_env().enabled)

    @app.post('/workspace/capture')
    def capture(body: Capture,owner=Depends(actor)):
        identity = service.ingest(owner,'owner',Incoming(account='web-capture',external_id=body.request_id,text=body.text))
        return {'source_version_id':identity,'result':service.process(owner,identity)}

    @app.get("/workspace/export")
    def export_data(owner=Depends(actor)):
        from .recovery import export_owner
        return JSONResponse(export_owner(factory, owner), headers={
            "Content-Disposition": 'attachment; filename="personal-crm-export.json"',
            "Cache-Control": "no-store",
        })

    @app.get("/workspace/tasks")
    def task_search(owner=Depends(actor), q: str = Query(default="", max_length=200),
                    state: Literal["active", "in_progress", "deferred", "done", "cancelled"] | None = None,
                    kind: Literal["task", "waiting", "note"] | None = None,
                    channel: Literal["owner", "forward", "mail"] | None = None,
                    project_id: str | None = None, undated: bool = False,
                    deadline: Literal["none", "overdue", "upcoming"] | None = None,
                    offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100)):
        with factory() as s:
            query = select(Task).where(Task.owner_id == owner)
            if q.strip():
                # SQL LIKE metacharacters are literal user text, not a search bypass.
                query = query.where(Task.title_search.contains(q.strip().casefold(), autoescape=True))
            if state:
                query = query.where(Task.state == state)
            if kind:
                query = query.where(Task.kind == kind)
            if project_id:
                project_for(s, owner, project_id)
                query = query.where(Task.project_id == project_id)
            if channel:
                query = query.join(SourceVersion, Task.source_version_id == SourceVersion.id).join(Source, Source.id == SourceVersion.source_id).where(Source.channel == channel)
            if undated or deadline == "none":
                query = query.where(Task.deadline["precision"].as_string().is_(None))
            elif deadline:
                precision = Task.deadline["precision"].as_string()
                value = Task.deadline["value"].as_string()
                timezone = Task.deadline["timezone"].as_string()
                late = case((precision == "instant", cast(value, DateTime(timezone=True)) < service.clock()),
                            (precision == "date", cast(value, Date) < cast(func.timezone(timezone, service.clock()), Date)), else_=False)
                query = query.where(Task.state.in_(["active", "in_progress"]), precision.is_not(None), late if deadline == "overdue" else ~late)
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            query = query.add_columns(Reminder).outerjoin(Reminder, (Reminder.task_id == Task.id) & Reminder.active.is_(True))
            rows = s.execute(query.order_by(Task.focused.desc(), Task.created_at.desc(), Task.id).offset(offset).limit(limit)).all()
            return {"items": [task_view(t, r) for t, r in rows], "total": total, "offset": offset, "limit": limit}

    @app.post("/workspace/tasks")
    def manual_create(body: ManualTask, owner=Depends(actor)):
        payload = body.model_dump(mode="json")
        with factory.begin() as s:
            profile = service.owner(s, owner)
            project_for(s, owner, body.project_id)
            at = reminder_instant(body.reminder_local, profile) if body.reminder_local else None
            deadline = local_deadline(body.deadline_local, profile) if body.deadline_local else body.deadline
            incoming = Incoming(external_id=body.request_id, account="web-form", text=body.title)
            version_id = service._ingest(s, owner, "owner", incoming, {"manual_fields": payload})
            version = s.get(SourceVersion, version_id)
            if (version.channel_metadata or {}).get("manual_fields") != payload:
                raise CRMError("source_revision_conflict")
            if version.status == "processed":
                task = service.task(s, owner, version.result["task"]["id"])
            else:
                output = Interpretation(source_version_id=version_id, operation="create", title=body.title,
                    kind=body.kind, obvious=True, reminder_at=at, deadline=deadline, planned_on=body.planned_on)
                task = service._create(s, owner, version_id, output, "explicit_web_create", version_id,
                                       allow_reminder=True, project_id=body.project_id)
                version.status, version.result = "processed", {"status": "created", "task": snapshot(task)}
            reminder = s.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True)))
            return task_view(task, reminder)

    @app.get("/workspace/tasks/{identity}")
    def task_detail(identity: str, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            task = service.task(s, owner, identity)
            version = s.get(SourceVersion, task.source_version_id)
            source = s.get(Source, version.source_id)
            reminder = s.scalar(select(Reminder).where(Reminder.task_id == identity, Reminder.active.is_(True)))
            history = [{"id": h.id, "task_version": h.task_version, "reason": h.reason, "before": h.before,
                        "after": h.after, "created_at": h.created_at} for h in s.scalars(select(History).where(
                            History.task_id == identity, History.owner_id == owner).order_by(History.created_at.desc(), History.task_version.desc()))]
            from .models import Recurrence
            from .recurrence import rule_view
            rule = s.scalar(select(Recurrence).where(Recurrence.id == task.recurrence_id, Recurrence.owner_id == owner)) if task.recurrence_id else None
            legacy = (version.channel_metadata or {}).get("legacy")
            return {**task_view(task, reminder), "source": {"id": version.id, "text": version.text, "channel": source.channel,
                    "received_at": version.received_at, "original_at": version.original_at}, "history": history,
                    "recurrence": rule_view(rule) if rule else None,
                    "legacy_import": {"reminder_at": legacy.get("remind_at"), "repeat_rule": legacy.get("repeat_rule")} if legacy and legacy.get("table") == "reminders" else None,
                    "children": [snapshot(child) for child in s.scalars(select(Task).where(Task.parent_task_id == identity,
                        Task.owner_id == owner).order_by(Task.step_batch.desc(), Task.step_index).limit(100))]}

    @app.patch("/workspace/tasks/{identity}")
    def task_edit(identity: str, body: TaskEdit, owner=Depends(actor)):
        with factory.begin() as s:
            profile = service.owner(s, owner)
            task = service.task(s, owner, identity, body.version)
            fields = body.model_fields_set - {"version"}
            if task.state in ("done", "cancelled") or not fields:
                raise CRMError("task_inactive" if fields else "empty_edit", 422)
            # All requested fields and generated reminder jobs share this transaction.
            if "title" in fields:
                if not body.title or not body.title.strip():
                    raise CRMError("title_required", 422)
                service._change(s, task, "title", CommandValues(title=body.title.strip()), "explicit_web_edit", uid())
            if "deadline" in fields:
                service._change(s, task, "deadline", CommandValues(deadline=body.deadline), "explicit_web_edit", uid())
            if "deadline_local" in fields:
                service._change(s, task, "deadline", CommandValues(deadline=local_deadline(body.deadline_local, profile)), "explicit_web_edit", uid())
            if "planned_on" in fields:
                service._change(s, task, "plan" if body.planned_on else "clear_plan", CommandValues(planned_on=body.planned_on), "explicit_web_edit", uid())
            if "project_id" in fields:
                project_for(s, owner, body.project_id)
                service._change(s, task, "project", CommandValues(project_id=body.project_id), "explicit_web_edit", uid())
            if "reminder_local" in fields:
                at = reminder_instant(body.reminder_local, profile) if body.reminder_local else None
                service._change(s, task, "reminder" if at else "clear_reminder", CommandValues(reminder_at=at), "explicit_web_edit", uid())
            reminder = s.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True)))
            return task_view(task, reminder)

    @app.get("/workspace/projects")
    def projects(owner=Depends(actor)):
        with factory() as s:
            counts = dict(s.execute(select(Task.project_id, func.count()).where(Task.owner_id == owner,
                Task.state.in_(["active", "in_progress", "deferred"]), Task.project_id.is_not(None)).group_by(Task.project_id)).all())
            return [{"id": p.id, "name": p.name, "description": p.description, "version": p.version,
                     "active_tasks": counts.get(p.id, 0)} for p in s.scalars(select(Project).where(Project.owner_id == owner).order_by(Project.created_at, Project.id))]

    @app.post("/workspace/projects")
    def project_create(body: ProjectInput, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            item = Project(owner_id=owner, name=body.name, description=body.description, created_at=service.clock())
            s.add(item)
            s.flush()
            return {"id": item.id, "name": item.name, "description": item.description, "version": item.version, "active_tasks": 0}

    @app.patch("/workspace/projects/{identity}")
    def project_edit(identity: str, body: ProjectEdit, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            item = project_for(s, owner, identity)
            if item.version != body.version:
                raise CRMError("version_conflict")
            item.name, item.description, item.version = body.name, body.description, item.version + 1
            return {"id": item.id, "name": item.name, "description": item.description, "version": item.version}

    @app.get("/workspace/inbox")
    def inbox(owner=Depends(actor)):
        with factory() as s:
            from .mail_api import evidence, proposal_view
            from .models import MailMessage
            proposals = [proposal_view(s, p)
                         for p in s.scalars(select(Proposal).where(Proposal.owner_id == owner, Proposal.status == "pending").order_by(Proposal.id))]
            questions = [{"id": d.id, "source_version_id": v.id, "text": v.text,
                          "question": (v.result or {}).get("question", "Уточните действие"), "expires_at": d.expires_at}
                         for d, v in s.execute(select(Dialogue, SourceVersion).join(SourceVersion, Dialogue.source_version_id == SourceVersion.id).where(
                             Dialogue.owner_id == owner, Dialogue.status == "pending", Dialogue.proposal_id.is_(None), Dialogue.expires_at > service.clock()).order_by(Dialogue.expires_at))]
            errors = [{"id": v.id, "text": v.text, "error_code": v.error_code, "retry_at": v.retry_at}
                      for v in s.scalars(select(SourceVersion).join(Source).where(Source.owner_id == owner,
                          SourceVersion.status == "error").order_by(SourceVersion.received_at.desc()).limit(100))]
            reviews = [{"id": v.id, "evidence": evidence(v)} for v in s.scalars(select(SourceVersion).join(Source)
                .join(MailMessage, MailMessage.source_id == Source.id).where(
                Source.owner_id == owner, MailMessage.owner_id == owner, Source.channel == "mail",
                SourceVersion.revision == MailMessage.revision, SourceVersion.status == "processed",
                SourceVersion.result["status"].as_string() == "review",
                SourceVersion.channel_metadata["cache_pruned"].as_boolean().is_not(True))
                .order_by(SourceVersion.received_at.desc()).limit(100)) if (v.result or {}).get("status") == "review"
                and not (v.channel_metadata or {}).get("cache_pruned")]
            return {"proposals": proposals, "questions": questions, "errors": errors, "mail_reviews": reviews}

    @app.post("/workspace/sources/{identity}/reply")
    def clarify_reply(identity: str, body: Reply, owner=Depends(actor)):
        with factory() as s:
            source = s.scalar(select(Source).join(SourceVersion).where(SourceVersion.id == identity, Source.owner_id == owner))
            if not source:
                raise CRMError("not_found", 404)
            account = source.account
        version_id = service.ingest(owner, "owner", Incoming(external_id=body.request_id, account=account, text=body.text),
                                    metadata={"reply_source_version_id": identity})
        return service.process(owner, version_id)

    def preferences_view(profile):
        return {"version": profile.version, "timezone": profile.timezone, "digest_hour": profile.digest_hour,
                "initiative_limit": profile.initiative_limit, "catchup_grace_seconds": profile.catchup_grace_seconds,
                "ai_paused": profile.ai_paused, "ai_budget_cap_micro_usd": profile.ai_budget_cap_micro_usd,
                "preferred_reminder_time": profile.preferred_reminder_time,
                "integrations": {"telegram_receive": settings.telegram.webhook_enabled, "telegram_send": settings.telegram.send_enabled,
                                 "mail": settings.mail.enabled and settings.mail.consent, "openai": settings.ai.enabled},
                "ai": {"model": settings.ai.model, "configured_budget_usd": settings.ai.monthly_budget_usd,
                       "consent_categories": sorted(settings.ai.consent_categories), "budget": BudgetLedger(factory, service.clock).status(profile.id)}}

    @app.get("/workspace/settings")
    def preferences(owner=Depends(actor)):
        with factory() as s:
            return preferences_view(s.get(Profile, owner))

    @app.patch("/workspace/settings")
    def preferences_edit(body: Preferences, owner=Depends(actor)):
        with factory.begin() as s:
            profile = service.owner(s, owner)
            if profile.version != body.version:
                raise CRMError("version_conflict")
            for field in body.model_fields_set - {"version"}:
                value = getattr(body, field)
                if field == "ai_budget_cap_micro_usd":
                    try:
                        maximum = micro_usd(settings.ai.monthly_budget_usd)
                    except AIError:
                        maximum = 0
                    if value is not None and value > maximum:
                        raise CRMError("budget_exceeds_server_limit", 422)
                elif value is None and field != "preferred_reminder_time":
                    raise CRMError("setting_value_required", 422)
                if field == "timezone":
                    try:
                        ZoneInfo(value)
                    except (ZoneInfoNotFoundError, ValueError):
                        raise CRMError("invalid_timezone", 422) from None
                setattr(profile, field, value)
            profile.version += 1
            # Pending digests follow the explicit preference, sent/unknown ones are not repeated.
            if profile.timezone:
                now = service.clock().astimezone(ZoneInfo(profile.timezone))
                scheduled = datetime.combine(now.date(), datetime.min.time(), ZoneInfo(profile.timezone)) + timedelta(hours=profile.digest_hour)
                for job in s.scalars(select(Job).where(Job.owner_id == owner, Job.kind == "digest", Job.status == "pending")):
                    job.run_at = scheduled
            result = {"version": profile.version}
        return preferences(owner)

    # A built application is served by the backend; development uses Vite's same-origin proxy.
    dist = Path.cwd() / "web" / "dist"
    if dist.is_dir():
        app.mount("/app", StaticFiles(directory=dist, html=True), name="web")

        @app.get("/", include_in_schema=False)
        def home():
            return RedirectResponse("/app/")
