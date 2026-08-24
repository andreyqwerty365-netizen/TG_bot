from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.ext import Application

from ..db import Database
from ..models import Reminder
from ..services.reminder_parser_ru import next_repeat_time
from ..utils.date_utils import local_to_utc, to_local, utc_now


@dataclass(slots=True)
class ActionResult:
    ok: bool
    reminder: Reminder | None = None
    message: str = ""


class ReminderService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _job_names(reminder_id: int) -> tuple[str, ...]:
        return (
            f"reminder:{reminder_id}",
            f"retry10:{reminder_id}",
            f"repeat5:{reminder_id}",
            f"check:{reminder_id}",
        )

    def cancel_jobs(self, app: Application, reminder_id: int) -> None:
        for name in self._job_names(reminder_id):
            for job in app.job_queue.get_jobs_by_name(name):
                job.schedule_removal()

    def complete(self, app: Application, chat_id: int, reminder_id: int) -> ActionResult:
        reminder = self.db.get_reminder(chat_id, reminder_id)
        if not reminder:
            self.cancel_jobs(app, reminder_id)
            return ActionResult(False, None, "Напоминание уже не существует.")
        if reminder.is_archived:
            self.cancel_jobs(app, reminder_id)
            return ActionResult(False, reminder, "Напоминание уже в архиве.")
        if reminder.done_at is not None:
            self.cancel_jobs(app, reminder_id)
            return ActionResult(False, reminder, "Это напоминание уже закрыто.")

        if reminder.repeat_rule:
            tz_offset = self.db.get_chat_settings(chat_id).tz_offset_minutes
            now_local = to_local(utc_now(), tz_offset).replace(tzinfo=None)
            next_local = next_repeat_time(
                to_local(reminder.remind_at, tz_offset).replace(tzinfo=None),
                reminder.repeat_rule,
            )
            while next_local <= now_local:
                next_local = next_repeat_time(next_local, reminder.repeat_rule)
            next_utc = local_to_utc(next_local, tz_offset)
            self.cancel_jobs(app, reminder_id)
            self.db.update_reminder_time(chat_id, reminder_id, next_utc)
            updated = self.db.get_reminder(chat_id, reminder_id)
            return ActionResult(True, updated, "repeat")

        self.cancel_jobs(app, reminder_id)
        self.db.mark_reminder_done(chat_id, reminder_id)
        updated = self.db.get_reminder(chat_id, reminder_id)
        return ActionResult(True, updated, "done")

    def snooze_minutes(self, app: Application, chat_id: int, reminder_id: int, minutes: int) -> ActionResult:
        reminder = self.db.get_reminder(chat_id, reminder_id)
        if not reminder:
            self.cancel_jobs(app, reminder_id)
            return ActionResult(False, None, "Напоминание уже не существует.")
        if reminder.is_archived or reminder.done_at is not None:
            self.cancel_jobs(app, reminder_id)
            return ActionResult(False, reminder, "Это напоминание уже неактуально.")
        new_utc = utc_now() + timedelta(minutes=minutes)
        self.cancel_jobs(app, reminder_id)
        self.db.update_reminder_time(chat_id, reminder_id, new_utc)
        updated = self.db.get_reminder(chat_id, reminder_id)
        return ActionResult(True, updated, "snoozed")

    def postpone_to_tomorrow(self, app: Application, chat_id: int, reminder_id: int) -> ActionResult:
        reminder = self.db.get_reminder(chat_id, reminder_id)
        if not reminder:
            self.cancel_jobs(app, reminder_id)
            return ActionResult(False, None, "Напоминание уже не существует.")
        if reminder.is_archived or reminder.done_at is not None:
            self.cancel_jobs(app, reminder_id)
            return ActionResult(False, reminder, "Это напоминание уже неактуально.")

        tz_offset = self.db.get_chat_settings(chat_id).tz_offset_minutes
        local_dt = to_local(reminder.remind_at, tz_offset).replace(tzinfo=None)
        tomorrow = to_local(utc_now(), tz_offset).date() + timedelta(days=1)
        tomorrow_same_time = datetime.combine(tomorrow, local_dt.time())
        new_utc = local_to_utc(tomorrow_same_time, tz_offset)
        self.cancel_jobs(app, reminder_id)
        self.db.update_reminder_time(chat_id, reminder_id, new_utc)
        updated = self.db.get_reminder(chat_id, reminder_id)
        return ActionResult(True, updated, "tomorrow")
