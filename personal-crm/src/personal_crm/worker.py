import argparse
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert

from .adapters import DeliveryError, FakeTransport
from .config import Settings
from .db import sessions
from .models import Attempt, Guidance, Job, Profile, Reminder, Task, uid, utcnow
from .accompaniment import (guidance_text, new_guidance, overview, prepare,
                            reconcile_uncertain_guidance, record_presentation, render_overview, resolve_guidance)
from .policy import notification_allowed


class Worker:
    def __init__(self, factory, transport, clock=utcnow, lease_seconds=30, max_attempts=3, owner_id=None):
        self.factory, self.transport, self.clock = factory, transport, clock
        self.lease_seconds, self.max_attempts = lease_seconds, max_attempts
        self.owner_id = owner_id

    def claim(self):
        now = self.clock()
        with self.factory.begin() as s:
            eligible = select(Job).where(
                or_(and_(Job.status == "pending", Job.run_at <= now),
                    and_(Job.status == "leased", Job.lease_until <= now))
            )
            if self.owner_id:
                eligible = eligible.where(Job.owner_id == self.owner_id)
            job = s.scalar(eligible.order_by(Job.run_at, Job.id).with_for_update(skip_locked=True).limit(1))
            if not job:
                return None
            pending = s.scalars(select(Attempt).where(Attempt.job_id == job.id, Attempt.outcome == "pending")).all()
            if pending:
                # A process could have died after transport; do not blindly send again.
                for attempt in pending:
                    attempt.outcome = "unknown"
                job.status, job.lease_token, job.lease_until = "unknown", None, None
                return None
            if job.attempts >= self.max_attempts:
                job.status = "failed"
                return None
            job.status, job.lease_token = "leased", uid()
            job.lease_until = now + timedelta(seconds=self.lease_seconds)
            return job.id, job.lease_token

    def _locked(self, s, job_id, token):
        identity = s.get(Job, job_id)
        if not identity:
            return None
        # All state-changing commands and deliveries use the same owner lock order.
        profile = s.scalar(select(Profile).where(Profile.id == identity.owner_id).with_for_update())
        reconcile_uncertain_guidance(s, profile)
        reminder = task = None
        if identity.reminder_id:
            reference = s.get(Reminder, identity.reminder_id)
            task = s.scalar(select(Task).where(Task.id == reference.task_id).with_for_update())
            reminder = s.scalar(select(Reminder).where(Reminder.id == reference.id).with_for_update())
        elif identity.guidance_id:
            guide = s.get(Guidance, identity.guidance_id)
            if guide.task_id:
                task = s.scalar(select(Task).where(Task.id == guide.task_id).with_for_update())
        job = s.scalar(select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True))
        if job.status != "leased" or job.lease_token != token or job.lease_until <= self.clock():
            return None
        if reminder and (not reminder.active or task.state in ("done", "cancelled", "deferred")
                         or reminder.version != job.reminder_version or task.version != reminder.task_version):
            job.status, job.lease_token, job.lease_until = "cancelled", None, None
            return None
        if job.guidance_id:
            guide = s.get(Guidance, job.guidance_id)
            if not guidance_text(s, guide, self.clock()):
                resolve_guidance(s, guide)
                return None
        if reminder and job.kind == "exact" and self.clock() - reminder.at > timedelta(seconds=profile.catchup_grace_seconds):
            job.status, job.cancel_reason, job.lease_token, job.lease_until = "cancelled", "missed_after_outage", None, None
            new_guidance(s, profile.id, "missed", f"missed:{job.id}", {"job_ids": [job.id]}, self.clock())
            return None
        return job, profile, task

    def _message(self, s, job, profile, task, ignore_attempt=None):
        if job.kind == "digest":
            view = overview(s, profile, self.clock(), ignore_attempt)
            payload = {"main_ids": [t["id"] for t in view["main"]],
                       "forgotten_ids": [t["id"] for t in view["forgotten"]],
                       "guidance_ids": [g["id"] for g in view["guidance"]],
                       "deadline_ids": [t["id"] for t in view["deadlines"]]}
            return render_overview(view), payload, view
        if job.guidance_id:
            guide = s.get(Guidance, job.guidance_id)
            view = {"forgotten": [], "guidance": [{"id": guide.id}]}
            return guidance_text(s, guide, self.clock()), {"guidance_ids": [guide.id]}, view
        text = task.title
        if job.kind == "exact":
            reminder = s.get(Reminder, job.reminder_id)
            if self.clock() - reminder.at >= timedelta(minutes=1):
                text = f"Опоздавшее напоминание: {text}"
        return text, {"task_id": task.id, "task_version": task.version}, None

    def deliver(self, job_id, token):
        now = self.clock()
        # Persist intent before the external side effect, independently of its outcome.
        with self.factory.begin() as s:
            locked = self._locked(s, job_id, token)
            if not locked:
                return "stale"
            job, profile, task = locked
            if s.scalar(select(Attempt.id).where(Attempt.job_id == job_id, Attempt.outcome == "pending")):
                return "busy"
            if job.kind == "digest" and (not profile.timezone or
                job.run_at.astimezone(ZoneInfo(profile.timezone)).date() !=
                now.astimezone(ZoneInfo(profile.timezone)).date()):
                job.status, job.lease_token, job.lease_until = "cancelled", None, None
                return "stale_digest"
            events = [(a.kind, a.started_at) for a in s.scalars(select(Attempt).where(
                Attempt.owner_id == job.owner_id, Attempt.outcome.in_(["success", "unknown", "pending"])
            ))]
            if not notification_allowed(job.kind, now, profile.timezone, events, profile.initiative_limit):
                job.status, job.lease_token, job.lease_until = "pending", None, None
                job.run_at = now + timedelta(minutes=5)
                return "limited"
            text, payload, view = self._message(s, job, profile, task)
            if not text:
                job.status = "cancelled"
                return "empty"
            attempt = Attempt(job_id=job.id, owner_id=job.owner_id, kind=job.kind,
                              started_at=now, local_day=now.astimezone(ZoneInfo(profile.timezone)).date()
                              if profile.timezone else None, payload=payload)
            s.add(attempt)
            s.flush()
            attempt_id = attempt.id
            job.attempts += 1
        # Recheck after intent commit, and hold locks through bounded fake delivery.
        # Future network transports must enforce a timeout shorter than the lease.
        with self.factory.begin() as s:
            locked = self._locked(s, job_id, token)
            attempt = s.get(Attempt, attempt_id)
            if not locked:
                attempt.outcome = "cancelled"
                return "stale"
            job, profile, task = locked
            events = [(a.kind, a.started_at) for a in s.scalars(select(Attempt).where(
                Attempt.owner_id == job.owner_id, Attempt.id != attempt.id,
                Attempt.outcome.in_(["success", "unknown", "pending"])
            ))]
            if not notification_allowed(job.kind, self.clock(), profile.timezone, events, profile.initiative_limit):
                attempt.outcome = "cancelled"
                job.status, job.lease_token, job.lease_until = "pending", None, None
                job.run_at = self.clock() + timedelta(minutes=5)
                return "limited"
            # Render again under locks: owner edits between intent and send cannot deliver stale text.
            text, payload, view = self._message(s, job, profile, task, attempt_id)
            if not text:
                attempt.outcome, job.status = "cancelled", "cancelled"
                return "empty"
            attempt.payload = payload
            attempt.started_at = self.clock()
            attempt.local_day = attempt.started_at.astimezone(ZoneInfo(profile.timezone)).date() if profile.timezone else None
            try:
                provider_id = self.transport.send(attempt.id, job.owner_id, text)
                attempt.outcome, attempt.provider_id, job.status = "success", provider_id, "sent"
            except DeliveryError:
                attempt.outcome = "error"
                job.status = "pending" if job.attempts < self.max_attempts else "failed"
                job.run_at = now + timedelta(seconds=60 * job.attempts)
            except Exception:
                attempt.outcome, job.status = "unknown", "unknown"
            job.lease_token, job.lease_until = None, None
            if attempt.outcome in ("success", "unknown") and view:
                record_presentation(s, view, self.clock(), attempt.outcome)
            if job.status == "sent" and job.reminder_id and job.kind in ("exact", "initiative"):
                s.execute(insert(Job).values(
                    id=uid(), owner_id=job.owner_id, reminder_id=job.reminder_id,
                    reminder_version=job.reminder_version, kind="repeat",
                    dedupe_key=f"repeat:{job.reminder_id}:{job.reminder_version}",
                    run_at=now + timedelta(hours=4), status="pending", attempts=0,
                ).on_conflict_do_nothing())
            return job.status

    def ensure_digest(self):
        prepare(self.factory, self.clock(), self.owner_id, digest=True)

    def tick(self, digest=False):
        prepare(self.factory, self.clock(), self.owner_id, digest=digest)
        claimed = self.claim()
        return self.deliver(*claimed) if claimed else "idle"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--owner", help="Restrict to one synthetic profile")
    parser.add_argument("--no-digest", action="store_true")
    args = parser.parse_args()
    worker = Worker(sessions(Settings.from_env().database_url), FakeTransport(), owner_id=args.owner)
    while True:
        try:
            result = worker.tick(digest=not args.no_digest)
        except SQLAlchemyError:
            # Do not print exception diagnostics: connection strings may contain secrets.
            result = "database_unavailable"
        print(f"fake worker outcome={result}", flush=True)
        if args.once:
            if result == "database_unavailable":
                raise SystemExit(1)
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
