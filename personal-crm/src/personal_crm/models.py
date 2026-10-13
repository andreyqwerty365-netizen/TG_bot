from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    JSON, String, Text, UniqueConstraint,
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
    digest_hour: Mapped[int] = mapped_column(default=12)
    initiative_limit: Mapped[int] = mapped_column(default=2)
    __table_args__ = (
        CheckConstraint("digest_hour BETWEEN 0 AND 23"),
        CheckConstraint("initiative_limit BETWEEN 0 AND 2"),
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
    parse_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (
        UniqueConstraint("source_id", "revision"),
        CheckConstraint("revision > 0"),
        CheckConstraint("status IN ('pending','processing','error','processed')"),
    )


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_versions.id"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), default="task")
    state: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(default=1)
    original_deadline: Mapped[dict | None] = mapped_column(JSON)
    deadline: Mapped[dict | None] = mapped_column(JSON)
    planned_on: Mapped[datetime | None] = mapped_column(Date)
    return_on: Mapped[datetime | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("kind IN ('task','waiting','note')"),
        CheckConstraint("state IN ('active','in_progress','deferred','done','cancelled')"),
        CheckConstraint("version > 0"),
    )


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
    kind: Mapped[str] = mapped_column(String(16))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    __table_args__ = (
        UniqueConstraint("owner_id", "dedupe_key"),
        CheckConstraint("kind IN ('exact','initiative','repeat','digest')"),
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
    __table_args__ = (CheckConstraint("outcome IN ('pending','success','error','unknown','cancelled')"),)
