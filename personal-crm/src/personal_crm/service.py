from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from .models import (AIBudget, Conversation, Dialogue, Guidance, History, Job, OutgoingReply, Profile,
                     Proposal, Reminder, Source, SourceVersion, Task, uid, utcnow)
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
    project_id: str | None = None


def snapshot(task):
    return {
        "id": task.id, "title": task.title, "kind": task.kind, "state": task.state,
        "version": task.version, "deadline": task.deadline,
        "original_deadline": task.original_deadline,
        "planned_on": task.planned_on.isoformat() if task.planned_on else None,
        "return_on": task.return_on.isoformat() if task.return_on else None,
        "focused": task.focused, "plan_postponements": task.plan_postponements,
        "draft_steps": task.draft_steps,
        "project_id": task.project_id,
    }


class CRMService:
    def __init__(self, factory, interpreter, clock=utcnow):
        self.factory, self.interpreter, self.clock = factory, interpreter, clock

    def register(self, owner_id, timezone=None, *, initialize_only=False):
        if not owner_id:
            raise CRMError("owner_not_configured", 503)
        if timezone:
            ZoneInfo(timezone)
        with self.factory.begin() as s:
            s.execute(insert(Profile).values(id=owner_id, timezone=timezone).on_conflict_do_nothing())
            current = s.get(Profile, owner_id)
            if timezone and current.timezone != timezone and not initialize_only:
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

    def ingest(self, owner_id, channel, incoming, *, metadata=None, received_at=None):
        # This transaction is committed before any interpreter invocation.
        with self.factory.begin() as s:
            self.owner(s, owner_id)
            return self._ingest(s, owner_id, channel, incoming, metadata, received_at)

    def _ingest(self, s, owner_id, channel, incoming, metadata=None, received_at=None):
        key = dict(owner_id=owner_id, channel=channel, account=incoming.account, external_id=incoming.external_id)
        s.execute(insert(Source).values(id=uid(), **key).on_conflict_do_nothing())
        source = s.scalar(select(Source).filter_by(**key).with_for_update())
        previous = s.scalar(select(SourceVersion).where(SourceVersion.source_id == source.id, SourceVersion.revision == incoming.revision))
        if previous:
            if previous.text != incoming.text or previous.original_at != incoming.original_at:
                raise CRMError("source_revision_conflict")
            return previous.id
        version = SourceVersion(source_id=source.id, revision=incoming.revision,
                                text=incoming.text, original_at=incoming.original_at,
                                received_at=received_at or self.clock(), channel_metadata=metadata)
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
            source_version.parse_attempts += 1
            source_version.retry_at = None
            source_version.parse_token = token
            source_version.parse_until = now + timedelta(minutes=1)
            text = source_version.text
        context = None
        trusted_rule = False
        try:
            if hasattr(self.interpreter, "interpret_context"):
                from .context import build_context
                from .language import deterministic
                with self.factory.begin() as s:
                    profile = self.owner(s, owner_id)
                    version = s.get(SourceVersion, version_id)
                    context = build_context(s, owner_id, s.get(Source, version.source_id), version, profile, self.clock())
                output = deterministic(context)
                trusted_rule = output is not None
                if output is None:
                    output = self.interpreter.interpret_context(context)
            else:
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
                result = self._apply_interpretation(s, owner_id, source, version, output, trusted_rule, context)
                self._finish_context(s, owner_id, source, version, output, result, trusted_rule)
                version.status, version.result, version.error_code = "processed", result, None
                version.retry_at = None
                version.parse_token, version.parse_until = None, None
                return result
        except Exception as error:
            # Do not expose model contents, stack traces, source texts or credentials.
            with self.factory.begin() as s:
                self.owner(s, owner_id)
                version = s.scalar(select(SourceVersion).where(SourceVersion.id == version_id).with_for_update())
                if version.parse_token == token:
                    allowed_codes = {"ai_disabled", "ai_consent_required", "ai_configuration_invalid", "ai_budget_limit",
                                     "ai_previous_attempt", "ai_timeout", "ai_refusal", "ai_incomplete", "ai_invalid_output", "ai_auth_error", "ai_rate_limit"}
                    code = getattr(error, "code", "interpretation_failed")
                    code = code if code in allowed_codes else "interpretation_failed"
                    version.status, version.error_code = "error", code
                    if code in ("interpretation_failed", "ai_rate_limit") and version.parse_attempts < 3:
                        version.retry_at = self.clock() + timedelta(seconds=60 * version.parse_attempts)
                    version.parse_token, version.parse_until = None, None
                    if hasattr(self.interpreter, "interpret_context"):
                        source = s.get(Source, version.source_id)
                        cursor = s.scalar(select(Conversation).where(Conversation.owner_id == owner_id,
                                          Conversation.account == source.account))
                        if not cursor:
                            cursor = Conversation(owner_id=owner_id, account=source.account)
                            s.add(cursor)
                        cursor.last_source_version_id = version.id
                    self._reply(s, owner_id, version, {"status": "error"})
            return {"status": "error", "source_version_id": version_id, "code": version.error_code or "interpretation_failed"}

    def recover_sources(self, owner_id, limit=16):
        """Resume source-first commits without requiring a second channel delivery."""
        with self.factory() as s:
            identities = s.scalars(select(SourceVersion.id).join(Source).where(
                Source.owner_id == owner_id,
                or_(SourceVersion.status == "pending", and_(SourceVersion.status == "processing",
                    SourceVersion.parse_until <= self.clock()), and_(SourceVersion.status == "error",
                    SourceVersion.parse_attempts < 3, SourceVersion.retry_at <= self.clock()))
            ).order_by(SourceVersion.received_at, SourceVersion.id).limit(limit)).all()
        processed = 0
        for identity in identities:
            result = self.process(owner_id, identity)
            if result["status"] not in ("error", "processing"):
                processed += 1
        return {"processed": processed}

    def _apply_interpretation(self, s, owner_id, source, version, output, trusted_rule=False, context=None):
        if output.operation in ("command", "answer", "overview"):
            if source.channel != "owner" or (not trusted_rule and output.operation != "overview"):
                raise CRMError("model_authority_rejected")
            if output.operation == "overview":
                from .accompaniment import overview
                return {"status": "overview", "overview": overview(s, s.get(Profile, owner_id), self.clock())}
            if output.operation == "answer":
                dialogue = self._bound_dialogue(s, owner_id, source.account, output.dialogue_id)
                if not dialogue or not dialogue.proposal_id:
                    return {"status": "clarification", "question": "Ответ не связан с актуальным предложением."}
                try:
                    result = self._confirm(s, owner_id, dialogue.proposal_id, dialogue.proposal_version, output.accepted)
                except CRMError as error:
                    if error.code != "proposal_conflict":
                        raise
                    result = {"status": "conflict", "code": "proposal_conflict"}
                dialogue.status = "stale" if result["status"] == "conflict" else "resolved"
                return result
            if context is None or not any(t.id == output.target_id for t in context.candidates):
                raise CRMError("unbound_command")
            task = self.task(s, owner_id, output.target_id)
            if task.version != output.target_version:
                if output.dialogue_id:
                    dialogue = self._bound_dialogue(s, owner_id, source.account, output.dialogue_id)
                    if dialogue:
                        dialogue.status = "stale"
                return {"status": "conflict", "code": "version_conflict"}
            self._change(s, task, output.change, output, "explicit_command", version.id)
            if output.dialogue_id:
                dialogue = self._bound_dialogue(s, owner_id, source.account, output.dialogue_id)
                if dialogue:
                    dialogue.status = "resolved"
            return {"status": "changed", "task": snapshot(task)}
        if output.operation == "clarify":
            return {"status": "clarification", "source_version_id": version.id, "question": output.question}
        payload = output.model_dump(mode="json")
        if output.operation == "propose_update":
            if context is not None and not any(t.id == output.target_id and t.version == output.target_version for t in context.candidates):
                raise CRMError("model_target_rejected")
            target = self.task(s, owner_id, output.target_id, output.target_version)
            proposal = Proposal(owner_id=owner_id, source_version_id=version.id,
                                task_id=target.id, expected_version=target.version, payload=payload)
        else:
            creation_version_id, creation_source = version.id, source
            if output.dialogue_id and trusted_rule:
                dialogue = self._bound_dialogue(s, owner_id, source.account, output.dialogue_id)
                if not dialogue or not dialogue.pending_action or dialogue.pending_action.get("operation") != "create":
                    return {"status": "conflict", "code": "dialogue_conflict"}
                origin = dialogue.pending_action.get("origin_source_version_id", dialogue.source_version_id)
                origin_version = s.scalar(select(SourceVersion).join(Source).where(SourceVersion.id == origin,
                    Source.owner_id == owner_id, Source.account == source.account, Source.channel == "owner"))
                if not origin_version:
                    raise CRMError("unbound_creation")
                creation_version_id, creation_source = origin_version.id, s.get(Source, origin_version.source_id)
            # An edited source creates a version-bound proposal, never a second active task.
            existing = s.scalar(select(Task).join(SourceVersion).where(
                SourceVersion.source_id == creation_source.id, Task.owner_id == owner_id
            ))
            if existing:
                change = ("reminder" if output.title == existing.title else "edit") if output.reminder_at else "title"
                payload.update(operation="propose_update", target_id=existing.id,
                               target_version=existing.version, change=change)
                proposal = Proposal(owner_id=owner_id, source_version_id=version.id,
                                    task_id=existing.id, expected_version=existing.version, payload=payload)
            elif source.channel != "mail" and output.obvious and (not output.reminder_at or (trusted_rule and source.channel == "owner")) and not (output.planned_on or output.return_on or output.focused is not None):
                task = self._create(s, owner_id, creation_version_id, output, "source", version.id,
                                    allow_reminder=trusted_rule and source.channel == "owner")
                return {"status": "created", "source_version_id": version.id, "task": snapshot(task)}
            else:
                proposal = Proposal(owner_id=owner_id, source_version_id=version.id, payload=payload)
        s.add(proposal)
        s.flush()
        return {"status": "proposal", "source_version_id": version.id,
                "proposal_id": proposal.id, "version": proposal.version, "proposal": payload,
                "target_title": self.task(s, owner_id, proposal.task_id).title if proposal.task_id else output.title}

    def _create(self, s, owner_id, source_version_id, output, reason, reference, allow_reminder=False, project_id=None):
        deadline = output.deadline.model_dump() if output.deadline else None
        task = Task(owner_id=owner_id, source_version_id=source_version_id, project_id=project_id,
                    title=output.title, kind=output.kind, original_deadline=deadline,
                    deadline=deadline, version=1, state="active", created_at=self.clock())
        task.draft_steps = output.draft_steps
        if output.planned_on or output.return_on:
            profile = s.get(Profile, owner_id)
            if not profile.timezone:
                raise CRMError("profile_timezone_required", 422)
            task.planned_on = output.planned_on
            if output.return_on:
                if output.return_on <= self.clock().astimezone(ZoneInfo(profile.timezone)).date():
                    raise CRMError("future_return_date_required", 422)
                task.state, task.return_on = "deferred", output.return_on
        if output.focused is not None:
            task.focused = output.focused
        s.add(task)
        s.flush()
        if output.reminder_at:
            # Model-created schedules are proposals; only explicit owner confirmation activates them.
            if not allow_reminder:
                raise CRMError("schedule_requires_owner_confirmation")
            self._schedule(s, task, output.reminder_at)
        self._history(s, task, None, "owner" if reason in ("confirmation", "explicit_web_create") else "source", reason, reference)
        return task

    def confirm(self, owner_id, proposal_id, proposal_version, accept=True):
        with self.factory.begin() as s:
            self.owner(s, owner_id)
            result = self._confirm(s, owner_id, proposal_id, proposal_version, accept)
        if result["status"] == "conflict":
            raise CRMError("version_conflict")
        return result

    def _confirm(self, s, owner_id, proposal_id, proposal_version, accept=True):
        proposal = s.scalar(select(Proposal).where(
            Proposal.id == proposal_id, Proposal.owner_id == owner_id
        ).with_for_update())
        if not proposal:
            raise CRMError("not_found", 404)
        if (proposal_version is not None and proposal.version != proposal_version) or proposal.status != "pending":
            raise CRMError("proposal_conflict")
        if not accept:
            proposal.status, proposal.version = "rejected", proposal.version + 1
            return {"status": "rejected"}
        output = Interpretation.model_validate(proposal.payload)
        if proposal.task_id:
            task = self.task(s, owner_id, proposal.task_id)
            if task.version != proposal.expected_version:
                proposal.status, proposal.version = "stale", proposal.version + 1
                return {"status": "conflict", "code": "version_conflict"}
            else:
                self._change(s, task, output.change, output, "confirmation", proposal.id)
        else:
            # Confirmation explicitly authorizes a proposed reminder as well as task creation.
            task = self._create(s, owner_id, proposal.source_version_id,
                                output, "confirmation", proposal.id, allow_reminder=True)
        proposal.status, proposal.version = "accepted", proposal.version + 1
        return {"status": "accepted", "task": snapshot(task)}

    def _bound_dialogue(self, s, owner_id, account, identity):
        return s.scalar(select(Dialogue).where(Dialogue.id == identity, Dialogue.owner_id == owner_id,
                         Dialogue.account == account, Dialogue.status == "pending", Dialogue.expires_at > self.clock()))

    def _finish_context(self, s, owner_id, source, version, output, result, trusted_rule=False):
        if hasattr(self.interpreter, "interpret_context"):
            cursor = s.scalar(select(Conversation).where(Conversation.owner_id == owner_id, Conversation.account == source.account))
            if not cursor:
                cursor = Conversation(owner_id=owner_id, account=source.account)
                s.add(cursor)
            cursor.last_source_version_id = version.id
            if result.get("task"):
                cursor.last_task_id = result["task"]["id"]
                if s.scalar(select(Reminder.id).where(Reminder.task_id == cursor.last_task_id, Reminder.active.is_(True))):
                    cursor.last_reminder_task_id = cursor.last_task_id
            if output.dialogue_id and trusted_rule and result["status"] in ("created", "changed", "accepted", "rejected"):
                previous = self._bound_dialogue(s, owner_id, source.account, output.dialogue_id)
                if previous:
                    previous.status = "resolved"
            if result["status"] in ("clarification", "proposal"):
                if output.dialogue_id and trusted_rule:
                    previous = self._bound_dialogue(s, owner_id, source.account, output.dialogue_id)
                    if previous:
                        previous.status = "resolved"
                proposal = s.get(Proposal, result.get("proposal_id")) if result.get("proposal_id") else None
                s.add(Dialogue(owner_id=owner_id, account=source.account, source_version_id=version.id,
                    proposal_id=proposal.id if proposal else None, task_id=proposal.task_id if proposal else output.target_id,
                    proposal_version=proposal.version if proposal else None,
                    expected_version=proposal.expected_version if proposal else output.target_version,
                    pending_action=output.pending_action, expires_at=self.clock() + timedelta(hours=24)))
        self._reply(s, owner_id, version, result)

    def _reply(self, s, owner_id, version, result):
        if not (version.channel_metadata or {}).get("reply_required"):
            return
        if s.scalar(select(OutgoingReply.id).where(OutgoingReply.source_version_id == version.id)):
            return
        from .replies import short_reply
        text = short_reply(result)
        budget = s.get(AIBudget, (owner_id, self.clock().astimezone(UTC).date().replace(day=1)))
        if budget and budget.warning_80:
            text += " Резерв или расходы ИИ достигли 80% месячного лимита; новые вызовы ограничены бюджетом."
        reply = OutgoingReply(owner_id=owner_id, source_version_id=version.id, text=text)
        s.add(reply)
        s.flush()
        s.add(Job(owner_id=owner_id, reply_id=reply.id, kind="reply", dedupe_key=f"reply:{version.id}", run_at=self.clock()))

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
        elif action == "edit" and values.title and values.reminder_at:
            task.title = values.title
        elif action == "clear_reminder":
            pass
        elif action == "clear_plan":
            task.planned_on = None
        elif action == "project":
            task.project_id = values.project_id
        elif action == "start":
            task.state, task.return_on = "in_progress", None
        elif action == "activate":
            task.state, task.return_on = "active", None
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
        if action in ("close", "cancel", "defer", "reminder", "edit", "clear_reminder"):
            self._cancel(s, task)
            if action in ("reminder", "edit"):
                self._schedule(s, task, values.reminder_at)
            elif action in ("close", "cancel", "defer"):
                self._cancel_guidance(s, task)
        else:
            # Existing reminder remains applicable to the explicitly revised task.
            s.execute(update(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True))
                      .values(task_version=task.version))
        if action in ("plan", "clear_plan"):
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
                      values.reminder_at.isoformat() if action in ("reminder", "edit") else None)

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
