from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from .models import Guidance, History, Job, Profile, Proposal, Reminder, Source, SourceVersion, Task, uid, utcnow
from .schema import Interpretation


class CRMError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass
class CommandValues:
    reminder_at: datetime | None = None
    deadline: object | None = None
    title: str | None = None
    planned_on: date | None = None
    return_on: date | None = None
    focused: bool | None = None


def snapshot(task):
    return {
        "id": task.id, "title": task.title, "kind": task.kind, "state": task.state,
        "version": task.version, "deadline": task.deadline,
        "original_deadline": task.original_deadline,
        "planned_on": task.planned_on.isoformat() if task.planned_on else None,
        "return_on": task.return_on.isoformat() if task.return_on else None,
        "focused": task.focused, "plan_postponements": task.plan_postponements,
    }


class CRMService:
    def __init__(self, factory, interpreter, clock=utcnow):
        self.factory, self.interpreter, self.clock = factory, interpreter, clock

    def register(self, owner_id, timezone=None):
        if not owner_id:
            raise CRMError("owner_not_configured", 503)
        if timezone:
            ZoneInfo(timezone)
        with self.factory.begin() as s:
            s.execute(insert(Profile).values(id=owner_id, timezone=timezone).on_conflict_do_nothing())
            current = s.get(Profile, owner_id)
            if timezone and current.timezone != timezone:
                raise CRMError("timezone_config_conflict")

    @staticmethod
    def owner(s, owner_id):
        profile = s.scalar(select(Profile).where(Profile.id == owner_id).with_for_update())
        if not profile:
            raise CRMError("owner_not_configured", 503)
        return profile

    @staticmethod
    def task(s, owner_id, task_id, version=None):
        task = s.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner_id).with_for_update())
        if not task:
            raise CRMError("not_found", 404)
        if version is not None and task.version != version:
            raise CRMError("version_conflict")
        return task

    def ingest(self, owner_id, channel, incoming):
        # This transaction is committed before any interpreter invocation.
        with self.factory.begin() as s:
            self.owner(s, owner_id)
            source_id = uid()
            key = dict(owner_id=owner_id, channel=channel, account=incoming.account, external_id=incoming.external_id)
            s.execute(insert(Source).values(id=source_id, **key).on_conflict_do_nothing())
            source = s.scalar(select(Source).filter_by(**key).with_for_update())
            previous = s.scalar(select(SourceVersion).where(
                SourceVersion.source_id == source.id, SourceVersion.revision == incoming.revision
            ))
            if previous:
                if previous.text != incoming.text or previous.original_at != incoming.original_at:
                    raise CRMError("source_revision_conflict")
                return previous.id
            version = SourceVersion(source_id=source.id, revision=incoming.revision,
                                    text=incoming.text, original_at=incoming.original_at,
                                    received_at=self.clock())
            s.add(version)
            s.flush()
            return version.id

    def process(self, owner_id, version_id):
        now, token = self.clock(), uid()
        with self.factory.begin() as s:
            source_version = s.scalar(select(SourceVersion).join(Source).where(
                SourceVersion.id == version_id, Source.owner_id == owner_id
            ).with_for_update(of=SourceVersion))
            if not source_version:
                raise CRMError("not_found", 404)
            if source_version.status == "processed":
                return source_version.result
            if source_version.status == "processing" and source_version.parse_until > now:
                return {"status": "processing", "source_version_id": version_id}
            source_version.status = "processing"
            source_version.parse_token = token
            source_version.parse_until = now + timedelta(minutes=1)
            text = source_version.text
        try:
            output = self.interpreter.interpret(version_id, text)
            output = Interpretation.model_validate(output)
            if output.source_version_id != version_id:
                raise CRMError("source_mismatch")
            with self.factory.begin() as s:
                self.owner(s, owner_id)
                version = s.scalar(select(SourceVersion).where(SourceVersion.id == version_id).with_for_update())
                if version.parse_token != token:
                    return {"status": "processing", "source_version_id": version_id}
                source = s.get(Source, version.source_id)
                result = self._apply_interpretation(s, owner_id, source, version, output)
                version.status, version.result, version.error_code = "processed", result, None
                version.parse_token, version.parse_until = None, None
                return result
        except Exception:
            # Do not expose model contents, stack traces, source texts or credentials.
            with self.factory.begin() as s:
                version = s.scalar(select(SourceVersion).where(SourceVersion.id == version_id).with_for_update())
                if version.parse_token == token:
                    version.status, version.error_code = "error", "interpretation_failed"
                    version.parse_token, version.parse_until = None, None
            return {"status": "error", "source_version_id": version_id, "code": "interpretation_failed"}

    def _apply_interpretation(self, s, owner_id, source, version, output):
        if output.operation == "clarify":
            return {"status": "clarification", "source_version_id": version.id, "question": output.question}
        payload = output.model_dump(mode="json")
        if output.operation == "propose_update":
            target = self.task(s, owner_id, output.target_id, output.target_version)
            proposal = Proposal(owner_id=owner_id, source_version_id=version.id,
                                task_id=target.id, expected_version=target.version, payload=payload)
        else:
            # An edited source creates a version-bound proposal, never a second active task.
            existing = s.scalar(select(Task).join(SourceVersion).where(
                SourceVersion.source_id == source.id
            ))
            if existing:
                payload.update(operation="propose_update", target_id=existing.id,
                               target_version=existing.version, change="title")
                proposal = Proposal(owner_id=owner_id, source_version_id=version.id,
                                    task_id=existing.id, expected_version=existing.version, payload=payload)
            elif source.channel != "mail" and output.obvious and not output.reminder_at:
                task = self._create(s, owner_id, version.id, output, "source", version.id)
                return {"status": "created", "source_version_id": version.id, "task": snapshot(task)}
            else:
                proposal = Proposal(owner_id=owner_id, source_version_id=version.id, payload=payload)
        s.add(proposal)
        s.flush()
        return {"status": "proposal", "source_version_id": version.id,
                "proposal_id": proposal.id, "version": proposal.version}

    def _create(self, s, owner_id, source_version_id, output, reason, reference):
        deadline = output.deadline.model_dump() if output.deadline else None
        task = Task(owner_id=owner_id, source_version_id=source_version_id,
                    title=output.title, kind=output.kind, original_deadline=deadline,
                    deadline=deadline, version=1, state="active", created_at=self.clock())
        s.add(task)
        s.flush()
        if output.reminder_at:
            # Model-created schedules are proposals; only explicit owner confirmation activates them.
            raise CRMError("schedule_requires_owner_confirmation")
        self._history(s, task, None, "owner" if reason == "confirmation" else "source", reason, reference)
        return task

    def confirm(self, owner_id, proposal_id, proposal_version, accept=True):
        conflict = False
        with self.factory.begin() as s:
            self.owner(s, owner_id)
            proposal = s.scalar(select(Proposal).where(
                Proposal.id == proposal_id, Proposal.owner_id == owner_id
            ).with_for_update())
            if not proposal:
                raise CRMError("not_found", 404)
            if proposal.version != proposal_version or proposal.status != "pending":
                raise CRMError("proposal_conflict")
            if not accept:
                proposal.status, proposal.version = "rejected", proposal.version + 1
                return {"status": "rejected"}
            output = Interpretation.model_validate(proposal.payload)
            if proposal.task_id:
                task = self.task(s, owner_id, proposal.task_id)
                if task.version != proposal.expected_version:
                    proposal.status, proposal.version = "stale", proposal.version + 1
                    conflict = True
                else:
                    self._change(s, task, output.change, output, "confirmation", proposal.id)
            else:
                # Confirmation explicitly authorizes a proposed reminder as well as task creation.
                reminder_at = output.reminder_at
                task = self._create(s, owner_id, proposal.source_version_id,
                                    output.model_copy(update={"reminder_at": None}), "confirmation", proposal.id)
                if reminder_at:
                    self._schedule(s, task, reminder_at)
            if not conflict:
                proposal.status, proposal.version = "accepted", proposal.version + 1
                result = {"status": "accepted", "task": snapshot(task)}
        if conflict:
            raise CRMError("version_conflict")
        return result

    def command(self, owner_id, task_id, version, action, *, at=None, deadline=None, title=None,
                planned_on=None, return_on=None, focused=None):
        if at is not None and at.tzinfo is None:
            raise CRMError("timezone_required", 422)
        with self.factory.begin() as s:
            self.owner(s, owner_id)
            task = self.task(s, owner_id, task_id, version)
            values = CommandValues(at.astimezone(UTC) if at else None, deadline, title, planned_on, return_on, focused)
            self._change(s, task, action, values, "explicit_command", uid())
            return snapshot(task)

    def _change(self, s, task, action, values, reason, reference):
        if task.state in ("done", "cancelled"):
            raise CRMError("task_inactive")
        before = snapshot(task)
        current_reminder = s.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True)))
        before["reminder_at"] = current_reminder.at.isoformat() if current_reminder else None
        if action == "close":
            task.state = "done"
        elif action == "reminder":
            if not values.reminder_at:
                raise CRMError("reminder_required", 422)
        elif action == "deadline":
            task.deadline = values.deadline.model_dump() if values.deadline else None
        elif action == "title" and values.title:
            task.title = values.title
        elif action == "cancel":
            task.state = "cancelled"
        elif action == "focus" and values.focused is not None:
            task.focused = values.focused
        elif action in ("plan", "defer"):
            profile = s.get(Profile, task.owner_id)
            if not profile.timezone:
                raise CRMError("profile_timezone_required", 422)
            today = self.clock().astimezone(ZoneInfo(profile.timezone)).date()
            if action == "plan":
                if not values.planned_on:
                    raise CRMError("execution_date_required", 422)
                if task.planned_on and values.planned_on > task.planned_on:
                    task.plan_postponements += 1
                task.planned_on = values.planned_on
            else:
                if not values.return_on or values.return_on <= today:
                    raise CRMError("future_return_date_required", 422)
                task.state, task.return_on = "deferred", values.return_on
        elif action == "resume" and task.state == "deferred":
            task.state, task.return_on = "active", None
        else:
            raise CRMError("forbidden_action", 422)
        task.version += 1
        task.last_discussed_at = self.clock()
        if action in ("close", "cancel", "defer", "reminder"):
            self._cancel(s, task)
            if action == "reminder":
                self._schedule(s, task, values.reminder_at)
            else:
                self._cancel_guidance(s, task)
        else:
            # Existing reminder remains applicable to the explicitly revised task.
            s.execute(update(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True))
                      .values(task_version=task.version))
        if action == "plan":
            ids = select(Reminder.id).where(Reminder.task_id == task.id)
            s.execute(update(Job).where(Job.reminder_id.in_(ids), Job.kind == "repeat",
                                       Job.status.in_(["pending", "leased"]))
                      .values(status="cancelled", cancel_reason="execution_plan_changed", lease_token=None, lease_until=None))
            if task.plan_postponements - task.obstacle_at_count >= 3:
                from .accompaniment import new_guidance
                self._cancel_guidance(s, task, kind="obstacle")
                task.obstacle_at_count = task.plan_postponements
                new_guidance(s, task.owner_id, "obstacle", f"obstacle:{task.id}:{task.plan_postponements}",
                             {"postponements": task.plan_postponements}, self.clock(), task)
        elif action == "deadline":
            self._cancel_guidance(s, task, kind="overdue")
        self._history(s, task, before, "owner", reason, reference,
                      values.reminder_at.isoformat() if action == "reminder" else None)

    def _schedule(self, s, task, at):
        reminder = Reminder(owner_id=task.owner_id, task_id=task.id,
                            task_version=task.version, at=at, version=1)
        s.add(reminder)
        s.flush()
        s.add(Job(owner_id=task.owner_id, reminder_id=reminder.id,
                  reminder_version=1, kind="exact", dedupe_key=f"exact:{reminder.id}", run_at=at))

    @staticmethod
    def _cancel(s, task):
        ids = select(Reminder.id).where(Reminder.task_id == task.id)
        s.execute(update(Reminder).where(Reminder.task_id == task.id).values(active=False))
        s.execute(update(Job).where(Job.reminder_id.in_(ids), Job.status.in_(["pending", "leased"]))
                  .values(status="cancelled", lease_token=None, lease_until=None))

    @staticmethod
    def _cancel_guidance(s, task, kind=None):
        from .accompaniment import resolve_guidance
        query = select(Guidance).where(Guidance.task_id == task.id, Guidance.status == "pending")
        if kind:
            query = query.where(Guidance.kind == kind)
        for guide in s.scalars(query):
            resolve_guidance(s, guide, "stale")

    def overview(self, owner_id):
        from .accompaniment import overview
        with self.factory.begin() as s:
            profile = self.owner(s, owner_id)
            return overview(s, profile, self.clock())

    def _history(self, s, task, before, actor, reason, reference, reminder_at=None):
        after = snapshot(task)
        current = s.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True)))
        after["reminder_at"] = reminder_at or (current.at.isoformat() if current else None)
        s.add(History(owner_id=task.owner_id, task_id=task.id, task_version=task.version,
                      actor=actor, reason=reason, reference=reference, before=before,
                      after=after, created_at=self.clock()))
