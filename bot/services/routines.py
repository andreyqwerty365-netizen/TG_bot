from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..db import Database
from ..models import RoutineTask
from ..utils.date_utils import to_local


@dataclass(slots=True)
class RoutineDayContext:
    routine_date: date
    shift_type: str
    wake_local: datetime


def find_routine_day(db: Database, chat_id: int, now_utc: datetime) -> RoutineDayContext | None:
    now_local = to_local(now_utc, db.get_chat_settings(chat_id).tz_offset_minutes)
    wake_times = db.get_shift_wake_times(chat_id)
    candidates = []
    for routine_date in (now_local.date(), now_local.date() - timedelta(days=1)):
        shift = db.get_shift_day(chat_id, routine_date)
        if shift is None:
            continue
        hh, mm = map(int, wake_times[shift.shift_type].split(":"))
        wake = datetime.combine(routine_date, time(hh, mm), tzinfo=now_local.tzinfo)
        if wake <= now_local < wake + timedelta(hours=24):
            candidates.append(RoutineDayContext(routine_date, shift.shift_type, wake))
    return max(candidates, key=lambda item: item.wake_local) if candidates else None


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
