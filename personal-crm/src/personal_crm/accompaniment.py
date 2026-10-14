"""Deterministic accompaniment. This module never interprets language or calls providers."""
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from .models import Attempt, Guidance, History, Job, Profile, Proposal, Reminder, Task, uid


def deadline_identity(deadline):
    value = {key: deadline[key] for key in ("precision", "value", "timezone")}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:32]


def overdue(deadline, now):
    if not deadline:
        return False
    if deadline["precision"] == "date":
        return now.astimezone(ZoneInfo(deadline["timezone"])).date() > date.fromisoformat(deadline["value"])
    return now > datetime.fromisoformat(deadline["value"])


def task_visible(task, profile, now):
    if task.recurrence_id and task.occurrence_on and now.astimezone(ZoneInfo(task.occurrence_timezone)).date() < task.occurrence_on:
        return False
    if task.state in ("active", "in_progress"):
        return True
    return (task.state == "deferred" and task.return_on is not None and profile.timezone is not None
            and task.return_on <= now.astimezone(ZoneInfo(profile.timezone)).date())


def new_guidance(s, owner_id, kind, event_key, payload, now, task=None):
    existing = s.scalar(select(Guidance).where(Guidance.owner_id == owner_id, Guidance.event_key == event_key))
    if existing:
        if existing.status == "stale" and kind == "overdue" and existing.id not in reserved_guidance(s, owner_id):
            existing.status, existing.task_version, existing.payload = "pending", task.version, payload
            job = s.scalar(select(Job).where(Job.guidance_id == existing.id))
            job.status, job.run_at, job.cancel_reason = "pending", now, None
            job.lease_token, job.lease_until, job.attempts = None, None, 0
        return existing
    guide = Guidance(owner_id=owner_id, kind=kind, event_key=event_key, payload=payload,
                     task_id=task.id if task else None, task_version=task.version if task else None,
                     status="pending", created_at=now)
    s.add(guide)
    s.flush()
    s.add(Job(owner_id=owner_id, guidance_id=guide.id, kind="initiative",
              dedupe_key=f"guide:{guide.id}", run_at=now))
    return guide


def resolve_guidance(s, guide, status="resolved"):
    guide.status = status
    s.execute(update(Job).where(Job.guidance_id == guide.id, Job.status.in_(["pending", "leased"]))
              .values(status="cancelled", cancel_reason="guidance_resolved", lease_token=None, lease_until=None))


def missed_items(s, guide):
    rows = s.execute(select(Job, Reminder, Task).select_from(Job)
        .join(Reminder, Job.reminder_id == Reminder.id).join(Task, Reminder.task_id == Task.id).where(
        Job.id.in_(guide.payload.get("job_ids", [])), Job.owner_id == guide.owner_id,
        Task.owner_id == guide.owner_id, Task.state.in_(["active", "in_progress"]),
        Reminder.active.is_(True),
        Job.cancel_reason == "missed_after_outage",
    )).all()
    return [{"job_id": job.id, "task_id": task.id, "task_version": task.version,
             "title": task.title, "scheduled_at": reminder.at.isoformat()} for job, reminder, task in rows]


def guidance_text(s, guide, now):
    if guide.status != "pending":
        return None
    if guide.kind == "missed":
        items = missed_items(s, guide)
        if not items:
            return None
        titles = "; ".join(item["title"][:160] for item in items[:3])
        return f"Во время простоя пропущено напоминаний: {len(items)}. {titles}. Дела сохранены; подробности в обзоре."
    task = s.get(Task, guide.task_id)
    if not task or task.owner_id != guide.owner_id or task.state not in ("active", "in_progress"):
        return None
    if guide.kind == "overdue":
        if not task.deadline or deadline_identity(task.deadline) != guide.payload["deadline_identity"] or not overdue(task.deadline, now):
            return None
        return f"Срок прошёл: {task.title[:160]}. Дело остаётся в обзоре; новый срок без вашего решения не назначен."
    return (f"План дела «{task.title[:160]}» переносился {guide.payload['postponements']} раза. "
            "Что мешает? Можно уменьшить шаг, оставить активным, отложить или отменить — выберите сами.")


def reserved_guidance(s, owner_id, ignore_attempt=None, unknown_only=False):
    outcomes = ["unknown"] if unknown_only else ["pending", "unknown"]
    query = select(Attempt).where(Attempt.owner_id == owner_id, Attempt.outcome.in_(outcomes))
    if ignore_attempt:
        query = query.where(Attempt.id != ignore_attempt)
    ids = set()
    for attempt in s.scalars(query):
        ids.update((attempt.payload or {}).get("guidance_ids", []))
    return ids


def reconcile_uncertain_guidance(s, profile):
    for identity in reserved_guidance(s, profile.id, unknown_only=True):
        guide = s.get(Guidance, identity)
        if guide and guide.owner_id == profile.id and guide.status == "pending":
            resolve_guidance(s, guide, "unknown")


def recover_pending_attempts(s, profile, now):
    rows = s.execute(select(Attempt, Job).select_from(Attempt).join(Job, Attempt.job_id == Job.id).where(
        Attempt.owner_id == profile.id, Attempt.outcome == "pending",
        or_(Job.status != "leased", Job.lease_until <= now),
    ).with_for_update(of=Job, skip_locked=True)).all()
    for attempt, job in rows:
        attempt.outcome = "unknown"
        if job.status == "leased":
            job.status, job.lease_token, job.lease_until = "unknown", None, None


def collect_missed(s, profile, now):
    pending_attempt = exists(select(Attempt.id).where(Attempt.job_id == Job.id, Attempt.outcome == "pending"))
    rows = s.execute(select(Job, Reminder, Task).select_from(Job)
        .join(Reminder, Job.reminder_id == Reminder.id).join(Task, Reminder.task_id == Task.id).where(
        Job.owner_id == profile.id, Job.kind == "exact", Reminder.active.is_(True),
        Task.state.in_(["active", "in_progress"]),
        or_(Job.status == "pending", (Job.status == "leased") & (Job.lease_until <= now)),
        Reminder.at < now - timedelta(seconds=profile.catchup_grace_seconds), ~pending_attempt,
    ).with_for_update(of=Job, skip_locked=True)).all()
    ids = []
    for job, reminder, task in rows:
        if reminder.task_version != task.version or reminder.version != job.reminder_version:
            job.status, job.cancel_reason = "cancelled", "stale_version"
            continue
        job.status, job.cancel_reason, job.lease_token, job.lease_until = "cancelled", "missed_after_outage", None, None
        ids.append(job.id)
    if not ids:
        return
    pending = s.scalar(select(Guidance).where(Guidance.owner_id == profile.id,
                                            Guidance.kind == "missed", Guidance.status == "pending"))
    if pending:
        pending.payload = {"job_ids": sorted(set(pending.payload["job_ids"] + ids))}
    else:
        key = hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()[:32]
        new_guidance(s, profile.id, "missed", f"missed:{key}", {"job_ids": ids}, now)


def prepare(factory, now, owner_id=None, digest=False):
    from .service import snapshot
    with factory() as s:
        owners = list(s.scalars(select(Profile.id).where(Profile.id == owner_id) if owner_id else select(Profile.id)))
    for identity in owners:
        with factory.begin() as s:
            profile = s.scalar(select(Profile).where(Profile.id == identity).with_for_update())
            recover_pending_attempts(s, profile, now)
            reconcile_uncertain_guidance(s, profile)
            if profile.timezone:
                today = now.astimezone(ZoneInfo(profile.timezone)).date()
                deferred = s.scalars(select(Task).where(Task.owner_id == identity, Task.state == "deferred",
                                                      Task.return_on <= today).with_for_update()).all()
                for task in deferred:
                    before = snapshot(task)
                    task.state, task.return_on, task.version = "active", None, task.version + 1
                    s.add(History(owner_id=identity, task_id=task.id, task_version=task.version,
                        actor="system", reason="scheduled_return", reference=uid(), before=before,
                        after=snapshot(task), created_at=now))
                for task in s.scalars(select(Task).where(Task.owner_id == identity,
                        Task.kind.in_(["task", "waiting"]), Task.state.in_(["active", "in_progress"]))):
                    if overdue(task.deadline, now):
                        key = deadline_identity(task.deadline)
                        new_guidance(s, identity, "overdue", f"overdue:{task.id}:{key}",
                                     {"deadline_identity": key}, now, task)
            collect_missed(s, profile, now)
            if digest and profile.timezone:
                local = now.astimezone(ZoneInfo(profile.timezone))
                scheduled = datetime.combine(local.date(), datetime.min.time(), ZoneInfo(profile.timezone))
                scheduled += timedelta(hours=profile.digest_hour)
                s.execute(insert(Job).values(id=uid(), owner_id=identity, kind="digest",
                    dedupe_key=f"digest:{local.date()}", run_at=scheduled,
                    status="pending", attempts=0).on_conflict_do_nothing())


def overview(s, profile, now, ignore_attempt=None):
    from .service import snapshot
    zone = ZoneInfo(profile.timezone) if profile.timezone else None
    today = now.astimezone(zone).date() if zone else None
    tasks = [t for t in s.scalars(select(Task).where(Task.owner_id == profile.id,
             Task.kind.in_(["task", "waiting"]))) if task_visible(t, profile, now)]
    by_id = {t.id: t for t in tasks}

    def deadline_order(task):
        value = task.deadline["value"]
        if task.deadline["precision"] == "instant":
            return datetime.fromisoformat(value).astimezone(zone or UTC).isoformat()
        return value

    dated = sorted([t for t in tasks if t.deadline], key=lambda t: (deadline_order(t), t.id))
    forgotten = sorted([t for t in tasks if t.kind == "task" and not t.deadline], key=lambda t: (
        max(t.last_presented_at or t.created_at, t.last_discussed_at or t.created_at), t.created_at, t.id))[:2]
    focused = sorted([t for t in tasks if t.focused], key=lambda t: (t.created_at, t.id))
    planned = sorted([t for t in tasks if today and t.planned_on == today], key=lambda t: (t.created_at, t.id))
    main = []
    upcoming = [t for t in dated if not overdue(t.deadline, now)]
    late = [t for t in dated if overdue(t.deadline, now)]
    for task in focused + upcoming + late + planned + forgotten:
        if task.id not in main and len(main) < 3:
            main.append(task.id)
    proposals = s.scalars(select(Proposal).where(Proposal.owner_id == profile.id, Proposal.status == "pending")).all()
    guides = []
    missed = []
    unavailable = reserved_guidance(s, profile.id, ignore_attempt)
    for guide in s.scalars(select(Guidance).where(Guidance.owner_id == profile.id, Guidance.status == "pending")):
        if guide.id in unavailable:
            continue
        message = guidance_text(s, guide, now)
        if message:
            guides.append({"id": guide.id, "kind": guide.kind, "task_id": guide.task_id,
                           "task_version": guide.task_version, "message": message})
            if guide.kind == "missed":
                missed.extend(missed_items(s, guide))
    return {
        "timezone": profile.timezone, "needs_timezone": zone is None,
        "planning_suggestions": planning_view(s, profile, now),
        "sync_errors": mail_sync_errors(s, profile.id),
        "main": [snapshot(by_id[identity]) for identity in main],
        "deadlines": [{**snapshot(t), "overdue": overdue(t.deadline, now)} for t in dated],
        "forgotten": [snapshot(t) for t in forgotten],
        "waiting": [snapshot(t) for t in tasks if t.kind == "waiting"],
        "proposals": [{"id": p.id, "version": p.version, "payload": p.payload} for p in proposals],
        "guidance": guides, "missed_reminders": missed, "other_count": len(tasks) - len(main),
    }


def render_overview(view):
    if not any(view.get(key) for key in ("main", "deadlines", "forgotten", "waiting", "proposals", "guidance", "sync_errors", "planning_suggestions")):
        return None
    sections = []
    if view["main"]:
        sections.append("Главные дела: " + "; ".join(t["title"][:160] for t in view["main"]))
    if view["deadlines"]:
        # Full owner overview retains every deadline; the message gives count and nearest three.
        dated = sorted(view["deadlines"], key=lambda t: (t["overdue"], t["deadline"]["value"]))
        sections.append("Сроки: " + "; ".join(
            f"{t['title'][:120]} — {t['deadline']['value']}" + (" (просрочено)" if t["overdue"] else "")
            for t in dated[:3]) + f". Всего дел со сроком: {len(dated)}")
    if view["forgotten"]:
        sections.append("Давно не возвращались: " + "; ".join(t["title"][:120] for t in view["forgotten"]))
    if view["waiting"]:
        sections.append(f"Ожиданий: {len(view['waiting'])}")
    if view["proposals"]:
        sections.append(f"Предложений для решения: {len(view['proposals'])}")
    if view.get("planning_suggestions"):
        sections.append(f"Предложений следующего шага и плана: {len(view['planning_suggestions'])}. Применяются после подтверждения в вебе.")
    sections.extend(error["message"] for error in view.get("sync_errors", []))
    sections.extend(g["message"] for g in view["guidance"])
    sections.append(f"Других дел: {view['other_count']}. Полный список доступен в обзоре.")
    return "\n".join(sections)


def mail_sync_errors(s, owner):
    from .models import MailAccount
    account = s.get(MailAccount, owner)
    if not account or not account.enabled or not account.error_code:
        return []
    message = "Почта: доступ отклонён, синхронизация остановлена. Проверьте подключение в настройках." if account.status == "auth_error" else "Почта: синхронизация задержана. Сохранённые предложения доступны; состояние в настройках."
    return [{"code": account.error_code, "message": message}]


def planning_view(s, profile, now):
    from .suggestions import pending
    return pending(s, profile, now)


def record_presentation(s, view, now, outcome):
    # Successful API delivery is presentation, never assumed reading or agreement.
    if outcome == "success":
        for item in view["forgotten"]:
            s.get(Task, item["id"]).last_presented_at = now
    for item in view["guidance"]:
        guide = s.get(Guidance, item["id"])
        if guide.status == "pending":
            guide.status = "sent" if outcome == "success" else "unknown"
            guide.delivered_at = now if outcome == "success" else None
            s.execute(update(Job).where(Job.guidance_id == guide.id, Job.status.in_(["pending", "leased"]))
                      .values(status="cancelled", cancel_reason="included_in_digest", lease_token=None, lease_until=None))
