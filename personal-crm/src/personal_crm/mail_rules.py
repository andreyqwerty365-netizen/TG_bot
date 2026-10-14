"""Conservative offline suggestions. Unrecognised content stays available for manual review."""
from datetime import date
import re

from sqlalchemy import select

from .models import MailMessage, Proposal, SourceVersion, Task
from .schema import Deadline, Interpretation


def interpret_mail(s, owner, source, version, timezone):
    meta = version.channel_metadata or {}
    thread = meta.get("mail_thread_id")
    if meta.get("content_incomplete") or not version.text.strip():
        return None, True
    # Quoted older correspondence and signatures do not become new promises.
    lines = []
    for line in version.text.splitlines():
        if re.match(r"\s*(?:On .+wrote:|В .+писал|От:|From:|--\s*$|_{5}|-{5}Original)", line, re.I):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    body = "\n".join(lines).strip()
    lowered = body.casefold()
    tasks = s.scalars(select(Task).join(SourceVersion, Task.source_version_id == SourceVersion.id)
        .join(MailMessage, MailMessage.source_id == SourceVersion.source_id).where(
            Task.owner_id == owner, MailMessage.owner_id == owner, MailMessage.thread_id == thread,
            Task.state.in_(["active", "in_progress", "deferred"]))).all()
    if len(tasks) > 1:
        return None, True
    target = tasks[0] if tasks else None
    deadline = None
    match = re.search(r"(?:до|срок|дедлайн|deadline|by)\s*[:—-]?\s*(\d{4}-\d{2}-\d{2})\b", lowered)
    if match and timezone:
        try:
            date.fromisoformat(match[1])
            deadline = Deadline(precision="date", value=match[1], original=match[0], timezone=timezone)
        except ValueError:
            return None, True
    negative = bool(re.search(r"\b(?:не|not|never|don't|ignore)\b", lowered))
    cancel = not negative and bool(re.search(r"(?:запрос|задача|поручение).{0,25}отмен[её]н|(?:request|task).{0,25}cancel(?:led|ed)", lowered))
    complete = not negative and bool(re.fullmatch(r"\s*(?:готово|выполнено|завершено|completed|done)[.!\s]*", lowered))
    request = bool(re.search(r"(?:пожалуйста[,\s]+\w+|прошу\s+\w+|please\s+\w+|could you\s+\w+)", lowered))
    promise = bool(re.search(r"\b(?:я\s+(?:подготовлю|пришлю|отправлю|сделаю|проверю)|i will\s+\w+)\b", lowered))
    if target:
        change = "cancel" if cancel else "close" if complete else "deadline" if deadline and deadline.model_dump() != target.deadline else None
        if change:
            return Interpretation(source_version_id=version.id, operation="propose_update", target_id=target.id,
                                  target_version=target.version, title=target.title, change=change, deadline=deadline), False
        return None, bool(request or promise or match)
    related = s.scalars(select(Proposal).join(SourceVersion, Proposal.source_version_id == SourceVersion.id)
        .join(MailMessage, MailMessage.source_id == SourceVersion.source_id).where(Proposal.owner_id == owner,
            MailMessage.owner_id == owner, MailMessage.thread_id == thread, Proposal.status == "pending",
            Proposal.source_version_id != version.id)).all()
    if cancel or complete or deadline or request or promise:
        for proposal in related:
            proposal.status, proposal.version = "stale", proposal.version + 1
    if cancel or complete:
        return None, bool(complete)
    if negative:
        return None, bool(request or promise)
    previous = related[-1].payload if len(related) == 1 else None
    if request or promise or (deadline and previous):
        title = re.sub(r"^(?:(?:re|fwd|fw):\s*)+", "", meta.get("subject", ""), flags=re.I).strip() or body[:300]
        if previous and not request and not promise:
            title = previous.get("title", title)
        kind = "waiting" if meta.get("direction") == "sent" and request and not promise else "task"
        return Interpretation(source_version_id=version.id, operation="create", title=title,
                              kind=kind, deadline=deadline), False
    # A recognised courtesy is irrelevant; otherwise explicitly expose unanalysed mail.
    courtesy = bool(re.fullmatch(r"(?:спасибо(?: за письмо)?|thank you|thanks)[.!\s]*", lowered))
    dangerous = bool(re.search(r"удали все|пароль|ignore previous|send.*password", lowered))
    return None, not (courtesy or dangerous or negative)
