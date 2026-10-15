"""Persistent operational status without private payloads."""
from datetime import timedelta

from sqlalchemy import func,select
from sqlalchemy.dialects.postgresql import insert

from .models import Job,WorkerStatus,utcnow

ERRORS={'source_unavailable','delivery_unavailable','backup_unavailable','remote_verification_failed','restore_hold'}


def record(factory,owner,role,state,*,error_code=None,success_at=None,now=None):
    if role not in ('source','delivery','backup') or state not in ('running','idle','disabled','error'):
        raise ValueError('invalid_worker_state')
    if error_code is not None and error_code not in ERRORS:
        raise ValueError('invalid_worker_error')
    now=now or utcnow()
    values=dict(owner_id=owner,role=role,state=state,last_seen_at=now,error_code=error_code)
    if success_at:
        values['last_success_at']=success_at
    with factory.begin() as s:
        s.execute(insert(WorkerStatus).values(**values).on_conflict_do_update(
            index_elements=['owner_id','role'],set_={k:v for k,v in values.items() if k not in ('owner_id','role')}))


def overview(factory,owner,*,now=None,delivery_enabled=False,backup_enabled=False):
    now=now or utcnow()
    with factory() as s:
        rows={r.role:r for r in s.scalars(select(WorkerStatus).where(WorkerStatus.owner_id==owner))}
        workers={}
        for role,enabled in [('source',True),('delivery',delivery_enabled),('backup',backup_enabled)]:
            row=rows.get(role)
            if not enabled:
                state='disabled'
            elif not row:
                state='missing'
            elif row.last_seen_at<now-timedelta(seconds=90) or row.last_seen_at>now+timedelta(seconds=60):
                state='stale'
            else:
                state=row.state
            workers[role]=dict(status=state,last_seen_at=row.last_seen_at.isoformat() if row else None,
                               error_code=row.error_code if row else None)
        queue={status:count for status,count in s.execute(select(Job.status,func.count()).where(Job.owner_id==owner).group_by(Job.status))}
        for status in ('pending','leased','sent','failed','unknown','cancelled'):
            queue.setdefault(status,0)
        oldest=s.scalar(select(func.min(Job.run_at)).where(Job.owner_id==owner,Job.status=='pending'))
        queue['oldest_pending_at']=oldest.isoformat() if oldest else None
        last=rows.get('backup').last_success_at if rows.get('backup') else None
        backup_status='disabled' if not backup_enabled else 'missing' if not last else 'overdue' if last<now-timedelta(hours=26) else 'verified'
        backup=dict(status=backup_status,last_verified_at=last.isoformat() if last else None,
                    error_code=rows.get('backup').error_code if rows.get('backup') else None)
    return dict(workers=workers,queue=queue,backup=backup)
