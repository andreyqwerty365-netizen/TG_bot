from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    JSON, String, Text, UniqueConstraint, event, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timezone: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    ai_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    recovery_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_budget_cap_micro_usd: Mapped[int | None] = mapped_column(BigInteger)
    preferred_reminder_time: Mapped[str | None] = mapped_column(String(5))
    digest_hour: Mapped[int] = mapped_column(default=12)
    initiative_limit: Mapped[int] = mapped_column(default=2)
    catchup_grace_seconds: Mapped[int] = mapped_column(default=3600, server_default="3600")
    __table_args__ = (
        CheckConstraint("digest_hour BETWEEN 0 AND 23"),
        CheckConstraint("initiative_limit BETWEEN 0 AND 2"),
        CheckConstraint("catchup_grace_seconds >= 0", name="ck_catchup_grace"),
    )


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    account: Mapped[str] = mapped_column(String(128))
    external_id: Mapped[str] = mapped_column(String(128))
    __table_args__ = (
        UniqueConstraint("owner_id", "channel", "account", "external_id"),
        CheckConstraint("channel IN ('owner', 'forward', 'mail')"),
    )


class MailAccount(Base):
    __tablename__ = "mail_accounts"
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    account_key: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="idle")
    cursor: Mapped[dict | None] = mapped_column(JSON)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(32))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, default=0)
    reset_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("status IN ('disabled','idle','syncing','backoff','auth_error','error')"),)


class MailMessage(Base):
    __tablename__ = "mail_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("mail_accounts.owner_id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str] = mapped_column(String(1000))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # A remote pointer is bookkeeping, not a credential or permission to mutate mail.
    pointer: Mapped[dict | None] = mapped_column(JSON)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("owner_id", "key"),)


class SourceVersion(Base):
    __tablename__ = "source_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    original_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(32))
    parse_token: Mapped[str | None] = mapped_column(String(36))
    parse_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON)
    channel_metadata: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (
        UniqueConstraint("source_id", "revision"),
        CheckConstraint("revision > 0"),
        CheckConstraint("status IN ('pending','processing','error','processed')"),
    )


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recurrence(Base):
    __tablename__ = "recurrences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    frequency: Mapped[str] = mapped_column(String(16))
    interval: Mapped[int] = mapped_column(Integer)
    anchor_on: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))
    reminder_time: Mapped[str | None] = mapped_column(String(5))
    template: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("frequency IN ('daily','weekly','monthly')", name="ck_recurrence_frequency"),
        CheckConstraint("interval BETWEEN 1 AND 365", name="ck_recurrence_interval"),
        CheckConstraint("status IN ('active','stopped')", name="ck_recurrence_status"),
    )


class RecurrenceHistory(Base):
    __tablename__ = "recurrence_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    recurrence_id: Mapped[str] = mapped_column(ForeignKey("recurrences.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("recurrence_id", "version"),)


class PlanningSuggestion(Base):
    __tablename__ = "planning_suggestions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int | None] = mapped_column(Integer)
    profile_version: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    event_key: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("owner_id", "event_key"),
        CheckConstraint("kind IN ('early','step','reminder_time')", name="ck_planning_kind"),
        CheckConstraint("status IN ('pending','accepted','dismissed','stale')", name="ck_planning_status"),
    )


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    recurrence_id: Mapped[str | None] = mapped_column(ForeignKey("recurrences.id"), index=True)
    occurrence_on: Mapped[date | None] = mapped_column(Date)
    occurrence_timezone: Mapped[str | None] = mapped_column(String(64))
    recurrence_warning: Mapped[str | None] = mapped_column(String(32))
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_batch: Mapped[int | None] = mapped_column(Integer)
    step_index: Mapped[int | None] = mapped_column(Integer)
    steps_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    promoted_steps_revision: Mapped[int | None] = mapped_column(Integer)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    title_search: Mapped[str] = mapped_column(Text, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16), default="task")
    state: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(default=1)
    original_deadline: Mapped[dict | None] = mapped_column(JSON)
    deadline: Mapped[dict | None] = mapped_column(JSON)
    planned_on: Mapped[date | None] = mapped_column(Date)
    return_on: Mapped[date | None] = mapped_column(Date)
    focused: Mapped[bool] = mapped_column(default=False, server_default="false")
    plan_postponements: Mapped[int] = mapped_column(default=0, server_default="0")
    obstacle_at_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_discussed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_presented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    draft_steps: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("kind IN ('task','waiting','note')"),
        CheckConstraint("state IN ('active','in_progress','deferred','done','cancelled')"),
        CheckConstraint("version > 0"),
        CheckConstraint("plan_postponements >= 0 AND obstacle_at_count >= 0", name="ck_postponement_counts"),
        UniqueConstraint("recurrence_id", "occurrence_on", name="uq_recurrence_occurrence"),
        UniqueConstraint("parent_task_id", "step_batch", "step_index", name="uq_plan_child"),
        Index("uq_recurrence_open", "recurrence_id", unique=True,
              postgresql_where=text("recurrence_id IS NOT NULL AND state IN ('active','in_progress','deferred')")),
    )


@event.listens_for(Task, "before_insert")
@event.listens_for(Task, "before_update")
def normalize_task_title(mapper, connection, task):
    task.title_search = task.title.casefold()


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), unique=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    expected_version: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = (CheckConstraint("status IN ('pending','accepted','rejected','stale')"),)


class History(Base):
    __tablename__ = "history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str] = mapped_column(String(36))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Guidance(Base):
    __tablename__ = "guidance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    event_key: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("owner_id", "event_key"),
        CheckConstraint("kind IN ('obstacle','overdue','missed')", name="ck_guidance_kind"),
        CheckConstraint("status IN ('pending','sent','unknown','resolved','stale')", name="ck_guidance_status"),
    )


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    reminder_id: Mapped[str | None] = mapped_column(ForeignKey("reminders.id"), index=True)
    reminder_version: Mapped[int | None] = mapped_column(Integer)
    guidance_id: Mapped[str | None] = mapped_column(ForeignKey("guidance.id", name="fk_jobs_guidance"), index=True)
    reply_id: Mapped[str | None] = mapped_column(ForeignKey("outgoing_replies.id", name="fk_jobs_reply"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    cancel_reason: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (
        UniqueConstraint("owner_id", "dedupe_key"),
        CheckConstraint("kind IN ('exact','initiative','repeat','digest','reply')", name="ck_job_kind"),
        CheckConstraint("status IN ('pending','leased','sent','cancelled','failed','unknown')"),
        Index("ix_jobs_claim", "status", "run_at"),
    )


class Attempt(Base):
    __tablename__ = "delivery_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_day: Mapped[datetime | None] = mapped_column(Date)
    outcome: Mapped[str] = mapped_column(String(16), default="pending")
    provider_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (CheckConstraint("outcome IN ('pending','success','error','unknown','cancelled')"),)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    account: Mapped[str] = mapped_column(String(128))
    last_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    last_reminder_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    last_source_version_id: Mapped[str | None] = mapped_column(ForeignKey("source_versions.id"))
    __table_args__ = (UniqueConstraint("owner_id", "account"),)


class Dialogue(Base):
    __tablename__ = "dialogues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    account: Mapped[str] = mapped_column(String(128))
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), unique=True)
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("proposals.id"))
    proposal_version: Mapped[int | None] = mapped_column(Integer)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    expected_version: Mapped[int | None] = mapped_column(Integer)
    pending_action: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('pending','resolved','expired','stale')", name="ck_dialogue_status"),)


class OutgoingReply(Base):
    __tablename__ = "outgoing_replies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), unique=True)
    text: Mapped[str] = mapped_column(Text)


class TelegramReceipt(Base):
    __tablename__ = "telegram_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    account: Mapped[str] = mapped_column(String(128))
    update_id: Mapped[int] = mapped_column(BigInteger)
    payload_digest: Mapped[str] = mapped_column(String(64))
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"))
    __table_args__ = (UniqueConstraint("owner_id", "account", "update_id"),)


class AIBudget(Base):
    __tablename__ = "ai_budgets"
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    limit_micro_usd: Mapped[int] = mapped_column(BigInteger)
    spent_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    reserved_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    warning_80: Mapped[bool] = mapped_column(default=False, server_default="false")
    __table_args__ = (CheckConstraint("limit_micro_usd > 0 AND spent_micro_usd >= 0 AND reserved_micro_usd >= 0", name="ck_ai_budget_nonnegative"),)


class AIReservation(Base):
    __tablename__ = "ai_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    period: Mapped[date] = mapped_column(Date)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), unique=True)
    model: Mapped[str] = mapped_column(String(128))
    amount_micro_usd: Mapped[int] = mapped_column(BigInteger)
    actual_micro_usd: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="reserved")
    output: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (CheckConstraint("status IN ('reserved','settled','unknown','failed')", name="ck_ai_reservation_status"),)
