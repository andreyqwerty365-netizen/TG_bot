from dataclasses import dataclass, field
from datetime import datetime
import re

from sqlalchemy import select, update

from .models import Conversation, Dialogue, Reminder, Source, SourceVersion, Task


@dataclass
class Candidate:
    id: str
    version: int
    title: str
    kind: str
    reminder_at: datetime | None = None


@dataclass
class Question:
    id: str
    source_version_id: str
    proposal_id: str | None
    task_id: str | None
    expected_version: int | None
    pending_action: dict | None


@dataclass
class SourceContext:
    owner_id: str
    source_version_id: str
    channel: str
    account: str
    text: str
    received_at: datetime
    original_at: datetime | None
    timezone: str | None
    candidates: list[Candidate] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    last_task_id: str | None = None
    reply_source_id: str | None = None
    last_source_id: str | None = None
    unsupported_media: bool = False
    reply_task_id: str | None = None
    candidates_complete: bool = True
    last_reminder_task_id: str | None = None


def build_context(s, owner_id, source, version, profile, now):
    s.execute(update(Dialogue).where(Dialogue.owner_id == owner_id, Dialogue.status == "pending",
                                   Dialogue.expires_at <= now).values(status="expired"))
    cursor = s.scalar(select(Conversation).where(Conversation.owner_id == owner_id, Conversation.account == source.account))
    metadata = version.channel_metadata or {}
    reply = metadata.get("reply_source_version_id")
    linked_version = s.scalar(select(SourceVersion).join(Source).where(SourceVersion.id == reply,
        Source.owner_id == owner_id, Source.account == source.account)) if reply else None
    if not linked_version:
        reply = None
    task_query = select(Task).where(Task.owner_id == owner_id, Task.state.in_(["active", "in_progress", "deferred"]))
    completion = re.fullmatch(r"(.+?) (?:обновил|выполнил|сделал|закончил)", version.text.lower().strip(" .!?"))
    subject = completion.group(1) if completion else ""
    words = {w for w in re.findall(r"[а-яёa-z]{3,}", subject) if w not in {"задачу", "задача", "дело", "последнее", "последнюю"}}
    if words:
        # Resolve against all owned rows before applying the provider's context cap.
        for word in words:
            task_query = task_query.where(Task.title_search.contains(word.casefold(), autoescape=True))
    elif "перенеси напоминание" in version.text.lower():
        task_query = task_query.where(select(Reminder.id).where(Reminder.task_id == Task.id, Reminder.active.is_(True)).exists())
    task_rows = s.scalars(task_query.order_by(Task.created_at.desc(), Task.id).limit(9)).all()
    complete = len(task_rows) <= 8
    tokens = set(re.findall(r"[а-яёa-z]{4,}", version.text.lower()))
    task_rows.sort(key=lambda task: (task.id != (cursor.last_task_id if cursor else None),
                                    -len(tokens & set(re.findall(r"[а-яёa-z]{4,}", task.title.lower())))))
    if cursor:
        # IDs are durable references, not hints limited to the newest rows.
        for identity in (cursor.last_task_id, cursor.last_reminder_task_id):
            linked_task = s.scalar(select(Task).where(Task.id == identity, Task.owner_id == owner_id,
                                   Task.state.in_(["active", "in_progress", "deferred"]))) if identity else None
            if linked_task and all(t.id != identity for t in task_rows):
                task_rows.insert(0, linked_task)
    if cursor and cursor.last_reminder_task_id:
        # Keep the explicit reminder cursor inside the bounded candidate set.
        task_rows.sort(key=lambda task: task.id != cursor.last_reminder_task_id)
    referenced = None
    if linked_version:
        referenced = s.scalar(select(Task).join(SourceVersion).where(Task.owner_id == owner_id,
                              SourceVersion.source_id == linked_version.source_id))
        if referenced:
            task_rows = [referenced] + [t for t in task_rows if t.id != referenced.id]
    candidates = []
    for task in task_rows[:8]:
        reminder = s.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.active.is_(True)))
        candidates.append(Candidate(task.id, task.version, task.title[:512], task.kind, reminder.at if reminder else None))
    questions = [Question(d.id, d.source_version_id, d.proposal_id, d.task_id, d.expected_version, d.pending_action)
                 for d in s.scalars(select(Dialogue).where(Dialogue.owner_id == owner_id, Dialogue.account == source.account,
                                                          Dialogue.status == "pending").order_by(
                     (Dialogue.source_version_id == (reply or (cursor.last_source_version_id if cursor else None))).desc(),
                     Dialogue.expires_at, Dialogue.id).limit(8))]
    return SourceContext(owner_id, version.id, source.channel, source.account, version.text, version.received_at,
                         version.original_at, profile.timezone, candidates, questions,
                         cursor.last_task_id if cursor else None, reply,
                         cursor.last_source_version_id if cursor else None, bool(metadata.get("unsupported_media")),
                         referenced.id if referenced else None, complete, cursor.last_reminder_task_id if cursor else None)
