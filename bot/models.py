from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class Note:
    id: int
    chat_id: int
    text: str
    created_at: datetime
    is_archived: bool


@dataclass(slots=True)
class Reminder:
    id: int
    chat_id: int
    text: str
    remind_at: datetime
    repeat_rule: str | None
    is_archived: bool
    done_at: datetime | None
    created_at: datetime


@dataclass(slots=True)
class ChatSettingsRecord:
    chat_id: int
    tz_offset_minutes: int
    dayplan_enabled: bool
    dayplan_time: str | None


@dataclass(slots=True)
class RoutineSettings:
    chat_id: int
    enabled: bool
    digest_interval_hours: int


@dataclass(slots=True)
class ShiftDay:
    chat_id: int
    routine_date: date
    shift_type: str


@dataclass(slots=True)
class RoutineDayStart:
    chat_id: int
    routine_date: date
    shift_type: str
    started_at: datetime


@dataclass(slots=True)
class RoutineTask:
    id: int
    chat_id: int
    text: str
    shift_type: str
    offset_minutes: int
    repeat_in_digest: bool
    expires_after_minutes: int
    is_active: bool
