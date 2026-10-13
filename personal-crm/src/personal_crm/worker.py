import argparse
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert

from .adapters import DeliveryError, FakeTransport
from .config import Settings
from .db import sessions
from .models import Attempt, Job, Profile, Proposal, Reminder, Task, uid, utcnow
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
        reminder = task = None
        if identity.reminder_id:
            reference = s.get(Reminder, identity.reminder_id)
            task = s.scalar(select(Task).where(Task.id == reference.task_id).with_for_update())
            reminder = s.scalar(select(Reminder).where(Reminder.id == reference.id).with_for_update())
        job = s.scalar(select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True))
        if job.status != "leased" or job.lease_token != token or job.lease_until <= self.clock():
            return None
        if reminder and (not reminder.active or task.state in ("done", "cancelled", "deferred")
                         or reminder.version != job.reminder_version or task.version != reminder.task_version):
            job.status, job.lease_token, job.lease_until = "cancelled", None, None
            return None
        return job, profile, task

    def deliver(self, job_id, token):
        now = self.clock()
        # Persist intent before the external side effect, independently of its outcome.
        with self.factory.begin() as s:
            locked = self._locked(s, job_id, token)
            if not locked:
                return "stale"
            job, profile, task = locked
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
            if job.kind == "digest":
                active = s.scalars(select(Task).where(Task.owner_id == job.owner_id,
                    Task.state.in_(["active", "in_progress"])).order_by(Task.created_at).limit(3)).all()
                proposal_count = len(s.scalars(select(Proposal.id).where(
                    Proposal.owner_id == job.owner_id, Proposal.status == "pending")).all())
                if not active and not proposal_count:
                    job.status = "cancelled"
                    return "empty"
                text = "План: " + "; ".join(t.title for t in active) + f". Предложений: {proposal_count}"
            else:
                text = task.title
            attempt = Attempt(job_id=job.id, owner_id=job.owner_id, kind=job.kind,
                              started_at=now, local_day=now.astimezone(ZoneInfo(profile.timezone)).date()
                              if profile.timezone else None)
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
            if job.status == "sent" and job.kind in ("exact", "initiative"):
                s.execute(insert(Job).values(
                    id=uid(), owner_id=job.owner_id, reminder_id=job.reminder_id,
                    reminder_version=job.reminder_version, kind="repeat",
                    dedupe_key=f"repeat:{job.reminder_id}:{job.reminder_version}",
                    run_at=now + timedelta(hours=4), status="pending", attempts=0,
                ).on_conflict_do_nothing())
            return job.status

    def ensure_digest(self):
        now = self.clock()
        with self.factory.begin() as s:
            profiles = select(Profile).where(Profile.timezone.is_not(None))
            if self.owner_id:
                profiles = profiles.where(Profile.id == self.owner_id)
            for profile in s.scalars(profiles):
                local = now.astimezone(ZoneInfo(profile.timezone))
                scheduled = datetime.combine(local.date(), datetime.min.time(), ZoneInfo(profile.timezone))
                scheduled += timedelta(hours=profile.digest_hour)
                s.execute(insert(Job).values(id=uid(), owner_id=profile.id, kind="digest",
                    dedupe_key=f"digest:{local.date()}", run_at=scheduled,
                    status="pending", attempts=0).on_conflict_do_nothing())

    def tick(self, digest=False):
        if digest:
            self.ensure_digest()
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
