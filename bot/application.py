from __future__ import annotations

import logging
import re
from datetime import timedelta
from functools import partial
from typing import Any
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters

from .config import Settings
from .db import Database
from .handlers import callbacks, commands, messages
from .services.organizer import build_last_screen, build_next_reminder_text, build_stats_text, build_today_plan, build_tomorrow_plan, cleanup_completed_reminders as archive_completed_reminders
from .services.reminder_actions import ReminderService
from .services.routines import digest_tasks, due_one_time_tasks, find_routine_day
from .services.search_text import build_search_text, search_records
from .state import ChatState, get_chat_state, set_mode
from .trainer.catalog import ExerciseCatalog
from .trainer.database import TrainerDatabase
from .trainer.handlers import TrainerHandlers
from .utils.date_utils import fmt_ru_date_or_time, fmt_ru_date_time, local_to_utc, to_local, utc_now
from .views import (
    INFO,
    MAIN,
    NOTES,
    PAGE_SIZE,
    REMINDERS,
    SETTINGS,
    build_notes_text,
    build_reminders_text,
    info_menu,
    main_menu,
    note_archive_card_kb,
    note_edit_card_kb,
    notes_archive_menu,
    notes_menu,
    reminder_archive_card_kb,
    reminder_edit_card_kb,
    reminder_fire_kb,
    reminders_menu,
    reminders_archive_menu,
    routine_checklist_kb,
    search_results_menu,
    settings_menu,
)

logger = logging.getLogger(__name__)
interaction_logger = logging.getLogger("bot.interactions")

ACTIVE_KEY = "active_message_id"
PLAN_KEY = "plan_message_id"
STATE_KEY = "chat_states"
SAFE_CALLBACK_SEGMENT_RE = re.compile(r"(?:[a-z_]+|\d+)")


def safe_callback_label(data: str | None) -> str:
    if not data:
        return "-"
    segments: list[str] = []
    for segment in data.split(":"):
        if not SAFE_CALLBACK_SEGMENT_RE.fullmatch(segment):
            segments.append("<redacted>")
            break
        segments.append(segment)
    return ":".join(segments)


class BotApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path, default_tz_offset_minutes=settings.default_tz_offset_minutes)
        self.reminders = ReminderService(self.db)
        trainer_db_path = settings.trainer_db_path or settings.db_path.with_name("workouts.sqlite3")
        exercises_path = settings.exercises_path
        if not exercises_path.is_absolute():
            exercises_path = Path(__file__).resolve().parents[1] / exercises_path
        self.trainer_database = TrainerDatabase(trainer_db_path)
        self.trainer_catalog = ExerciseCatalog(exercises_path)
        self.trainer = TrainerHandlers(
            self.trainer_database,
            self.trainer_catalog,
            ZoneInfo(settings.trainer_timezone),
        )

    def build(self) -> Application:
        if not self.settings.bot_token:
            raise RuntimeError("BOT_TOKEN не найден. Укажи переменную окружения BOT_TOKEN.")
        if not self.settings.allowed_user_ids:
            raise RuntimeError("BOT_ALLOWED_USER_IDS не найден. Укажи Telegram user ID владельца.")

        self.db.init()
        self.trainer_database.init()
        app = Application.builder().token(self.settings.bot_token).build()
        app.bot_data["db"] = self.db
        app.bot_data["settings"] = self.settings
        app.bot_data[STATE_KEY] = {}
        app.bot_data[ACTIVE_KEY] = {}
        app.bot_data[PLAN_KEY] = {}

        app.add_handler(TypeHandler(Update, self.log_update), group=-2)
        app.add_handler(TypeHandler(Update, self.require_allowed_user), group=-1)
        app.add_handler(CommandHandler("start", partial(commands.cmd_start, self)))
        app.add_handler(CommandHandler("help", partial(commands.cmd_help, self)))
        app.add_handler(CommandHandler("today", partial(commands.cmd_today, self)))
        app.add_handler(CommandHandler("next", partial(commands.cmd_next, self)))
        app.add_handler(CommandHandler("tomorrow", partial(commands.cmd_tomorrow, self)))
        app.add_handler(CommandHandler("last", partial(commands.cmd_last, self)))
        app.add_handler(CommandHandler("new", partial(commands.cmd_new, self)))
        app.add_handler(CommandHandler("notes", partial(commands.cmd_notes, self)))
        app.add_handler(CommandHandler("reminders", partial(commands.cmd_reminders, self)))
        app.add_handler(CommandHandler("cleanup_done", partial(commands.cmd_cleanup_done, self)))
        app.add_handler(CommandHandler("search", partial(commands.cmd_search, self)))
        app.add_handler(CommandHandler("settings", partial(commands.cmd_settings, self)))
        app.add_handler(CommandHandler("tz", partial(commands.cmd_tz, self)))
        app.add_handler(CommandHandler("export", partial(commands.cmd_export, self)))
        app.add_handler(CommandHandler("import", partial(commands.cmd_import, self)))
        app.add_handler(CommandHandler("stats", partial(commands.cmd_stats, self)))
        app.add_handler(CommandHandler("trainer", partial(self.trainer.command_trainer, self)))
        app.add_handler(CommandHandler("workout", partial(self.trainer.command_workout, self)))
        app.add_handler(CommandHandler("workout_history", partial(self.trainer.command_history, self)))
        app.add_handler(CommandHandler("workout_export", partial(self.trainer.command_export, self)))
        app.add_handler(CommandHandler("cancel", partial(self.trainer.command_cancel, self)))
        app.add_handler(CallbackQueryHandler(partial(callbacks.on_button, self)))
        app.add_handler(MessageHandler(filters.VOICE, partial(messages.on_voice, self)))
        app.add_handler(MessageHandler(filters.Document.ALL, partial(messages.on_document, self)))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, partial(messages.on_text, self)))
        app.post_init = self.post_init
        app.add_error_handler(self.on_error)
        return app

    async def log_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        state = None
        if chat_id is not None:
            try:
                state = self.get_chat_state(context, chat_id).mode
            except Exception:
                state = None

        if update.callback_query:
            interaction_logger.info(
                "mode=%s event=callback data=%s",
                state or "-",
                safe_callback_label(update.callback_query.data),
            )
            return
        if update.message:
            if update.message.text:
                interaction_logger.info(
                    "mode=%s event=text chars=%s",
                    state or "-",
                    len(update.message.text),
                )
            elif update.message.voice:
                interaction_logger.info(
                    "mode=%s event=voice seconds=%s",
                    state or "-",
                    update.message.voice.duration,
                )
            elif update.message.document:
                interaction_logger.info(
                    "mode=%s event=document",
                    state or "-",
                )

    def is_user_allowed(self, user_id: int | None) -> bool:
        return user_id in self.settings.allowed_user_ids

    async def require_allowed_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        user_id = user.id if user else None
        if self.is_user_allowed(user_id):
            return

        logger.warning("Blocked unauthorized Telegram user")
        if update.callback_query:
            try:
                await update.callback_query.answer("Нет доступа.", show_alert=True)
            except Exception:
                pass
        elif update.effective_chat:
            try:
                await context.bot.send_message(update.effective_chat.id, "Нет доступа.")
            except Exception:
                pass
        raise ApplicationHandlerStop

    async def post_init(self, app: Application) -> None:
        try:
            await app.bot.set_my_commands(
                [
                    BotCommand("start", "Главное меню"),
                    BotCommand("today", "План на сегодня"),
                    BotCommand("new", "Быстрая запись"),
                    BotCommand("notes", "Заметки"),
                    BotCommand("reminders", "Напоминания"),
                    BotCommand("search", "Поиск"),
                    BotCommand("settings", "Настройки"),
                    BotCommand("trainer", "Персональный тренер"),
                    BotCommand("workout", "Записать тренировку"),
                    BotCommand("workout_history", "История тренировок"),
                    BotCommand("workout_export", "Экспорт тренировок"),
                    BotCommand("export", "Экспорт данных"),
                    BotCommand("help", "Помощь"),
                ]
            )
        except Exception:
            logger.warning("Failed to register Telegram command menu", exc_info=True)
        for reminder in self.db.list_pending_reminders():
            self.schedule_reminder(app, reminder.id)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT chat_id, tz_offset_minutes, dayplan_enabled, dayplan_time FROM chat_settings WHERE dayplan_enabled=1 AND dayplan_time IS NOT NULL"
            ).fetchall()
        for row in rows:
            self.schedule_dayplan(app, int(row["chat_id"]), int(row["tz_offset_minutes"]), str(row["dayplan_time"]))
        self.sync_routine_tick(app)

    def get_chat_state(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> ChatState:
        store: dict[int, ChatState] = context.application.bot_data[STATE_KEY]
        return get_chat_state(store, chat_id)

    def set_mode(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, mode: str | None, **payload: Any) -> ChatState:
        store: dict[int, ChatState] = context.application.bot_data[STATE_KEY]
        return set_mode(store, chat_id, mode, **payload)

    async def send_active(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None) -> int:
        active_map: dict[int, int] = context.application.bot_data[ACTIVE_KEY]
        old_message_id = active_map.get(chat_id) or self.db.get_active_message_id(chat_id)
        if old_message_id:
            try:
                await context.bot.delete_message(chat_id, old_message_id)
            except Exception:
                try:
                    await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=old_message_id, reply_markup=None)
                except Exception:
                    pass
        msg = await context.bot.send_message(chat_id, text, reply_markup=reply_markup)
        active_map[chat_id] = msg.message_id
        self.db.set_active_message_id(chat_id, msg.message_id)
        return msg.message_id

    async def update_or_send_plan(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
        plan_map: dict[int, int] = context.application.bot_data[PLAN_KEY]
        msg_id = plan_map.get(chat_id)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")]])
        if msg_id:
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=keyboard)
                return
            except Exception:
                pass
        msg = await context.bot.send_message(chat_id, text, reply_markup=keyboard)
        plan_map[chat_id] = msg.message_id

    def schedule_reminder(self, app: Application, reminder_id: int) -> None:
        reminder = self.db.get_reminder(self._chat_id_for_reminder(reminder_id), reminder_id)
        if reminder is None:
            return
        self.reminders.cancel_jobs(app, reminder_id)
        when = reminder.remind_at if reminder.remind_at > utc_now() else utc_now()
        app.job_queue.run_once(
            self.fire_reminder_job,
            when=when,
            data={"chat_id": reminder.chat_id, "reminder_id": reminder.id},
            name=f"reminder:{reminder.id}",
        )

    def schedule_delivery_retry(self, app: Application, chat_id: int, reminder_id: int) -> None:
        name = f"retry10:{reminder_id}"
        for job in app.job_queue.get_jobs_by_name(name):
            job.schedule_removal()
        app.job_queue.run_once(
            self.retry_reminder_job,
            when=timedelta(minutes=10),
            data={"chat_id": chat_id, "reminder_id": reminder_id},
            name=name,
        )

    def _chat_id_for_reminder(self, reminder_id: int) -> int:
        with self.db.connect() as conn:
            row = conn.execute("SELECT chat_id FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        return int(row["chat_id"]) if row else 0

    def schedule_dayplan(self, app: Application, chat_id: int, tz_offset_minutes: int, hhmm: str) -> None:
        name = f"dayplan:{chat_id}"
        for job in app.job_queue.get_jobs_by_name(name):
            job.schedule_removal()
        try:
            hh, mm = map(int, hhmm.split(":"))
        except ValueError:
            logger.warning("Skipped invalid day plan time")
            return
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            logger.warning("Skipped invalid day plan time")
            return
        now_local = to_local(utc_now(), tz_offset_minutes)
        next_local = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if next_local <= now_local:
            from datetime import timedelta

            next_local = next_local + timedelta(days=1)
        next_utc = local_to_utc(next_local.replace(tzinfo=None), tz_offset_minutes)
        app.job_queue.run_repeating(self.dayplan_job, interval=86400, first=next_utc, data={"chat_id": chat_id}, name=name)

    def sync_dayplan_schedule(self, app: Application, chat_id: int) -> None:
        settings = self.db.get_chat_settings(chat_id)
        name = f"dayplan:{chat_id}"
        for job in app.job_queue.get_jobs_by_name(name):
            job.schedule_removal()
        if settings.dayplan_enabled and settings.dayplan_time:
            self.schedule_dayplan(app, chat_id, settings.tz_offset_minutes, settings.dayplan_time)

    def sync_routine_tick(self, app: Application) -> None:
        for job in app.job_queue.get_jobs_by_name("routine:tick"):
            job.schedule_removal()
        if self.db.list_enabled_routine_chat_ids():
            app.job_queue.run_repeating(self.routine_tick_job, interval=60, first=10, data={}, name="routine:tick")

    async def routine_tick_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        now = utc_now()
        for chat_id in self.db.list_enabled_routine_chat_ids():
            routine_day = find_routine_day(self.db, chat_id, now)
            if routine_day is None:
                continue
            one_time = due_one_time_tasks(self.db, chat_id, now)
            settings = self.db.get_routine_settings(chat_id)
            elapsed_minutes = int((to_local(now, self.db.get_chat_settings(chat_id).tz_offset_minutes) - routine_day.wake_local).total_seconds() // 60)
            interval_minutes = settings.digest_interval_hours * 60
            delivery_key = None
            repeating = []
            if elapsed_minutes >= interval_minutes:
                slot = elapsed_minutes // interval_minutes
                delivery_key = f"digest:{routine_day.routine_date}:{slot}"
                if not self.db.has_routine_delivery(chat_id, delivery_key):
                    repeating = digest_tasks(self.db, chat_id, now)

            tasks = one_time + repeating
            if not tasks:
                continue
            heading = "📋 Осталось на сегодня:" if repeating else "🌅 Пора выполнить:"
            text = heading + "\n" + "\n".join(f"{idx}. {task.text}" for idx, task in enumerate(tasks, 1))
            await self.send_active(context, chat_id, text, reply_markup=routine_checklist_kb(tasks, routine_day.routine_date))
            for task in one_time:
                self.db.record_routine_delivery(chat_id, f"task:{routine_day.routine_date}:{task.id}")
            if repeating and delivery_key:
                self.db.record_routine_delivery(chat_id, delivery_key)

    async def fire_reminder_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = int(context.job.data["chat_id"])
        reminder_id = int(context.job.data["reminder_id"])
        reminder = self.db.get_reminder(chat_id, reminder_id)
        if not reminder or reminder.is_archived or reminder.done_at:
            self.reminders.cancel_jobs(context.application, reminder_id)
            return
        self.schedule_delivery_retry(context.application, chat_id, reminder_id)
        interaction_logger.info("event=reminder_delivery id=%s attempt=initial", reminder_id)
        await self._send_reminder_notification(context, reminder)

    async def retry_reminder_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = int(context.job.data["chat_id"])
        reminder_id = int(context.job.data["reminder_id"])
        reminder = self.db.get_reminder(chat_id, reminder_id)
        if not reminder or reminder.is_archived or reminder.done_at:
            self.reminders.cancel_jobs(context.application, reminder_id)
            return
        interaction_logger.info("event=reminder_delivery id=%s attempt=retry10", reminder_id)
        await self._send_reminder_notification(context, reminder)

    async def _send_reminder_notification(self, context: ContextTypes.DEFAULT_TYPE, reminder) -> None:
        settings = self.db.get_chat_settings(reminder.chat_id)
        text = f"⏰ Напоминание\n{fmt_ru_date_time(reminder.remind_at, settings.tz_offset_minutes)} — {reminder.text}"
        await self.send_active(context, reminder.chat_id, text, reply_markup=reminder_fire_kb(reminder.id))

    async def dayplan_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = int(context.job.data["chat_id"])
        await context.bot.send_message(chat_id, build_today_plan(self.db, chat_id))

    def notes_screen(self, chat_id: int) -> str:
        return self.notes_page_screen(chat_id)[0]

    def reminders_screen(self, chat_id: int) -> str:
        return self.reminders_page_screen(chat_id)[0]

    def next_reminder_screen(self, chat_id: int) -> str:
        return build_next_reminder_text(self.db, chat_id)

    def tomorrow_screen(self, chat_id: int) -> str:
        return build_tomorrow_plan(self.db, chat_id)

    def cleanup_completed_reminders(self, chat_id: int) -> int:
        return archive_completed_reminders(self.db, chat_id)

    def notes_archive_screen(self, chat_id: int, archived_notes=None) -> str:
        notes = archived_notes if archived_notes is not None else self.db.list_notes(chat_id, archived=True, limit=20)
        return build_notes_text(notes, archived=True)

    def reminders_archive_screen(self, chat_id: int) -> str:
        settings = self.db.get_chat_settings(chat_id)
        reminders = self.db.list_reminders(chat_id, archived=True, include_done=True, limit=20)
        return build_reminders_text(reminders, settings.tz_offset_minutes, archived=True)

    async def show_notes_menu(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        text, keyboard = self.notes_page_screen(chat_id)
        await self.send_active(context, chat_id, text, reply_markup=keyboard)

    async def show_reminders_menu(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        text, keyboard = self.reminders_page_screen(chat_id)
        await self.send_active(context, chat_id, text, reply_markup=keyboard)

    def notes_page_screen(self, chat_id: int, page: int = 0, *, archived: bool = False):
        total = self.db.count_notes(chat_id, archived=archived)
        page = self._normalize_page(page, total)
        notes = self.db.list_notes(chat_id, archived=archived, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
        text = build_notes_text(notes, archived=archived, page=page, total=total)
        keyboard = notes_archive_menu(notes, page=page, total=total) if archived else notes_menu(notes, page=page, total=total)
        return text, keyboard

    def reminders_page_screen(self, chat_id: int, page: int = 0, *, archived: bool = False):
        tz_offset = self.db.get_chat_settings(chat_id).tz_offset_minutes
        include_done = archived
        total = self.db.count_reminders(chat_id, archived=archived, include_done=include_done)
        page = self._normalize_page(page, total)
        reminders = self.db.list_reminders(
            chat_id,
            archived=archived,
            include_done=include_done,
            limit=PAGE_SIZE,
            offset=page * PAGE_SIZE,
        )
        text = build_reminders_text(reminders, tz_offset, archived=archived, page=page, total=total)
        keyboard = (
            reminders_archive_menu(reminders, page=page, total=total)
            if archived
            else reminders_menu(reminders, page=page, total=total)
        )
        return text, keyboard

    def search_screen(self, chat_id: int, needle: str):
        notes, reminders = search_records(self.db, chat_id, needle)
        return build_search_text(self.db, chat_id, needle, notes=notes, reminders=reminders), search_results_menu(notes, reminders)

    @staticmethod
    def _normalize_page(page: int, total: int) -> int:
        return min(max(0, page), max(0, (total - 1) // PAGE_SIZE))

    async def show_note_edit_card(self, query, chat_id: int, note_id: int) -> None:
        note = self.db.get_note(chat_id, note_id)
        if not note:
            await query.edit_message_text("Заметка не найдена или уже устарела.", reply_markup=notes_menu())
            return
        if note.is_archived:
            await self.show_note_archive_card(query, chat_id, note_id)
            return
        await query.edit_message_text(f"Заметка:\n\n{note.text}", reply_markup=note_edit_card_kb(note_id))

    async def show_note_archive_card(self, query, chat_id: int, note_id: int) -> None:
        note = self.db.get_note(chat_id, note_id)
        if not note:
            await query.edit_message_text("Заметка не найдена или уже устарела.", reply_markup=notes_menu())
            return
        if not note.is_archived:
            await self.show_note_edit_card(query, chat_id, note_id)
            return
        await query.edit_message_text(f"Архивная заметка:\n\n{note.text}", reply_markup=note_archive_card_kb(note_id))

    async def show_reminder_edit_card(self, query, chat_id: int, reminder_id: int) -> None:
        reminder = self.db.get_reminder(chat_id, reminder_id)
        if not reminder:
            await query.edit_message_text("Напоминание не найдено или уже устарело.", reply_markup=reminders_menu())
            return
        if reminder.is_archived:
            await self.show_reminder_archive_card(query, chat_id, reminder_id)
            return
        settings = self.db.get_chat_settings(chat_id)
        repeat = reminder.repeat_rule or "нет"
        await query.edit_message_text(
            f"Напоминание:\n{fmt_ru_date_time(reminder.remind_at, settings.tz_offset_minutes)}\n{reminder.text}\nПовтор: {repeat}",
            reply_markup=reminder_edit_card_kb(reminder_id),
        )

    async def show_reminder_archive_card(self, query, chat_id: int, reminder_id: int) -> None:
        reminder = self.db.get_reminder(chat_id, reminder_id)
        if not reminder:
            await query.edit_message_text("Напоминание не найдено или уже устарело.", reply_markup=reminders_menu())
            return
        if not reminder.is_archived:
            await self.show_reminder_edit_card(query, chat_id, reminder_id)
            return
        settings = self.db.get_chat_settings(chat_id)
        await query.edit_message_text(
            f"Архивное напоминание:\n{fmt_ru_date_time(reminder.remind_at, settings.tz_offset_minutes)}\n{reminder.text}",
            reply_markup=reminder_archive_card_kb(reminder_id),
        )

    async def complete_reminder_from_callback(self, query, context: ContextTypes.DEFAULT_TYPE, chat_id: int, reminder_id: int) -> None:
        result = self.reminders.complete(context.application, chat_id, reminder_id)
        if not result.ok:
            await query.edit_message_text(f"ℹ️ {result.message}", reply_markup=main_menu())
            return
        if result.message == "repeat" and result.reminder:
            self.schedule_reminder(context.application, result.reminder.id)
            settings = self.db.get_chat_settings(chat_id)
            await query.edit_message_text(
                f"✅ Готово. Следующее срабатывание: {fmt_ru_date_time(result.reminder.remind_at, settings.tz_offset_minutes)}",
                reply_markup=main_menu(),
            )
            return
        await query.edit_message_text("✅ Выполнено.", reply_markup=main_menu())

    async def snooze_reminder_from_callback(self, query, context: ContextTypes.DEFAULT_TYPE, chat_id: int, reminder_id: int, minutes: int) -> None:
        result = self.reminders.snooze_minutes(context.application, chat_id, reminder_id, minutes)
        if not result.ok or not result.reminder:
            await query.edit_message_text(f"ℹ️ {result.message}", reply_markup=main_menu())
            return
        self.schedule_reminder(context.application, result.reminder.id)
        settings = self.db.get_chat_settings(chat_id)
        await query.edit_message_text(
            f"⏰ Перенёс на {fmt_ru_date_time(result.reminder.remind_at, settings.tz_offset_minutes)}",
            reply_markup=main_menu(),
        )

    async def move_reminder_to_tomorrow_from_callback(self, query, context: ContextTypes.DEFAULT_TYPE, chat_id: int, reminder_id: int) -> None:
        result = self.reminders.postpone_to_tomorrow(context.application, chat_id, reminder_id)
        if not result.ok or not result.reminder:
            await query.edit_message_text(f"ℹ️ {result.message}", reply_markup=main_menu())
            return
        self.schedule_reminder(context.application, result.reminder.id)
        settings = self.db.get_chat_settings(chat_id)
        await query.edit_message_text(
            f"📅 Перенёс: {fmt_ru_date_or_time(result.reminder.remind_at, settings.tz_offset_minutes)}",
            reply_markup=main_menu(),
        )

    async def toggle_dayplan(self, query, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        settings = self.db.get_chat_settings(chat_id)
        new_enabled = not settings.dayplan_enabled
        time_value = settings.dayplan_time or "08:00"
        self.db.set_dayplan(chat_id, new_enabled, time_value)
        self.sync_dayplan_schedule(context.application, chat_id)
        from .views import dayplan_menu

        await query.edit_message_text("Настройки плана дня", reply_markup=dayplan_menu(new_enabled))

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled bot error", exc_info=context.error)
        chat_id = None
        if isinstance(update, Update) and update.effective_chat:
            chat_id = update.effective_chat.id
        if chat_id is not None:
            try:
                await self.send_active(context, chat_id, "Бот словил ошибку. Я её залогировал. Повтори действие ещё раз.", reply_markup=main_menu())
            except Exception:
                logger.exception("Failed to notify user about error")


def create_application(settings: Settings) -> Application:
    return BotApp(settings).build()


