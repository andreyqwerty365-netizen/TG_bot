from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
