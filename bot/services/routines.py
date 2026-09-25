from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..db import Database
from ..models import RoutineTask
from ..utils.date_utils import to_local


@dataclass(slots=True)
class RoutineDayContext:
    routine_date: date
    shift_type: str
    wake_local: datetime


def find_routine_day(db: Database, chat_id: int, now_utc: datetime) -> RoutineDayContext | None:
    started = db.get_latest_routine_day_start(chat_id)
    if started is None or started.started_at > now_utc:
        return None
    if started.ended_at is not None and started.ended_at <= now_utc:
        return None
    wake_local = to_local(started.started_at, db.get_chat_settings(chat_id).tz_offset_minutes)
    return RoutineDayContext(started.routine_date, started.shift_type, wake_local)


def _eligible(db: Database, chat_id: int, now_utc: datetime):
    context = find_routine_day(db, chat_id, now_utc)
    if context is None:
        return None, []
    now_local = to_local(now_utc, db.get_chat_settings(chat_id).tz_offset_minutes)
    statuses = db.get_routine_task_statuses(chat_id, context.routine_date)
    tasks = []
    for task in db.list_routine_tasks(chat_id, context.shift_type):
        due = context.wake_local + timedelta(minutes=task.offset_minutes)
        expires = context.wake_local + timedelta(minutes=task.expires_after_minutes)
        if due <= now_local <= expires and task.id not in statuses:
            tasks.append(task)
    return context, tasks


def due_one_time_tasks(db: Database, chat_id: int, now_utc: datetime) -> list[RoutineTask]:
    context, tasks = _eligible(db, chat_id, now_utc)
    if context is None:
        return []
    return [task for task in tasks if not task.repeat_in_digest and not db.has_routine_delivery(chat_id, f"task:{context.routine_date}:{task.id}")]


def digest_tasks(db: Database, chat_id: int, now_utc: datetime) -> list[RoutineTask]:
    _, tasks = _eligible(db, chat_id, now_utc)
    return [task for task in tasks if task.repeat_in_digest]


def pending_tasks(db: Database, chat_id: int, now_utc: datetime) -> list[RoutineTask]:
    _, tasks = _eligible(db, chat_id, now_utc)
    return tasks
