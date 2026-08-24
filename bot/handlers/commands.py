from __future__ import annotations

import json
from io import BytesIO
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from ..services.import_export import build_export_payload
from ..services.organizer import build_last_screen, build_stats_text, build_today_plan, parse_tz_offset
from ..views import cancel_kb, main_menu, quick_last_kb, quick_new_kb, settings_menu

if TYPE_CHECKING:
    from ..application import BotApp


async def cmd_start(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    app.get_chat_state(context, chat_id).menu = "main"
    app.set_mode(context, chat_id, None)
    await app.send_active(
        context,
        chat_id,
        "Личный помощник. Напиши одну фразу: без времени сохраню заметку, с временем создам напоминание.",
        reply_markup=main_menu(),
    )


async def cmd_help(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (
        "Как пользоваться:\n"
        "• напиши мысль — сохраню заметку\n"
        "• напиши 'завтра в 9 отчёт' или 'напомни вечером оплатить счёт' — создам напоминание\n"
        "• в конце можно добавить /every day, /every week или /every month\n\n"
        "Команды:\n"
        "/today — план на сегодня\n"
        "/next — ближайшее активное напоминание\n"
        "/tomorrow — план на завтра\n"
        "/last — последние записи\n"
        "/new — быстрый ввод\n"
        "/notes — последние заметки\n"
        "/reminders — активные напоминания\n"
        "/cleanup_done — убрать завершённые из активного списка\n"
        "/search <текст> — поиск по заметкам и напоминаниям\n"
        "/settings — настройки\n"
        "/tz — текущая таймзона или её смена\n"
        "/export и /import — резервная копия секретаря\n"
        "/trainer — открыть персонального тренера\n"
        "/workout — записать тренировку\n"
        "/workout_history — история тренировок\n"
        "/workout_export — выгрузить тренировки в Excel\n"
        "/cancel — отменить ввод тренировки"
    )
    await app.send_active(context, chat_id, text, reply_markup=main_menu())


async def cmd_today(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await app.update_or_send_plan(context, update.effective_chat.id, build_today_plan(app.db, update.effective_chat.id))


async def cmd_next(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await app.send_active(context, chat_id, app.next_reminder_screen(chat_id), reply_markup=main_menu())


async def cmd_tomorrow(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await app.send_active(context, chat_id, app.tomorrow_screen(chat_id), reply_markup=main_menu())


async def cmd_last(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await app.send_active(context, chat_id, build_last_screen(app.db, chat_id), reply_markup=quick_last_kb())


async def cmd_new(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    app.set_mode(context, chat_id, "waiting_quick_entry")
    await app.send_active(
        context,
        chat_id,
        "Пришли одну фразу.\n• идея для проекта\n• через 30м позвонить\n• напомни вечером оплатить счёт",
        reply_markup=quick_new_kb(),
    )


async def cmd_notes(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    app.get_chat_state(context, chat_id).menu = "notes"
    await app.show_notes_menu(context, chat_id)


async def cmd_reminders(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    app.get_chat_state(context, chat_id).menu = "reminders"
    await app.show_reminders_menu(context, chat_id)


async def cmd_cleanup_done(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    cleaned = app.cleanup_completed_reminders(chat_id)
    text = f"✅ Убрано в архив {cleaned} завершённых напоминаний." if cleaned else "Завершённых напоминаний для очистки нет."
    await app.send_active(context, chat_id, text, reply_markup=main_menu())


async def cmd_settings(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    app.get_chat_state(context, chat_id).menu = "settings"
    settings = app.db.get_chat_settings(chat_id)
    await app.send_active(context, chat_id, "⚙️ Настройки", reply_markup=settings_menu(settings.dayplan_enabled))


async def cmd_tz(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        settings = app.db.get_chat_settings(chat_id)
        sign = "+" if settings.tz_offset_minutes >= 0 else "-"
        hh = abs(settings.tz_offset_minutes) // 60
        mm = abs(settings.tz_offset_minutes) % 60
        await app.send_active(context, chat_id, f"Текущая таймзона: UTC{sign}{hh:02d}:{mm:02d}", reply_markup=main_menu())
        return

    raw = context.args[0].strip()
    offset = parse_tz_offset(raw)
    if offset is None:
        await app.send_active(context, chat_id, "Неверный формат. Пример: /tz +3, /tz -5, /tz +3:30", reply_markup=main_menu())
        return

    app.db.set_timezone(chat_id, offset)
    app.sync_dayplan_schedule(context.application, chat_id)
    await app.send_active(context, chat_id, f"✅ Таймзона сохранена: UTC{raw}", reply_markup=main_menu())


async def cmd_export(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await send_export(app, context, chat_id)


async def send_export(app: "BotApp", context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    payload = build_export_payload(app.db, chat_id)
    buffer = BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    buffer.name = "telegram-assistant-export.json"
    await app.send_active(context, chat_id, "✅ Экспорт готов. Файл отправлен ниже.", reply_markup=main_menu())
    await context.bot.send_document(chat_id=chat_id, document=buffer, caption=buffer.name)


async def cmd_import(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    app.set_mode(context, chat_id, "waiting_import")
    await app.send_active(context, chat_id, "Пришли JSON-файл экспорта документом.", reply_markup=cancel_kb("menu:main"))


async def cmd_stats(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await app.send_active(context, chat_id, build_stats_text(app.db, chat_id), reply_markup=main_menu())


async def cmd_search(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        app.set_mode(context, chat_id, "waiting_search_query")
        await app.send_active(context, chat_id, "Пришли текст для поиска по заметкам и напоминаниям.", reply_markup=cancel_kb("menu:main"))
        return

    query = " ".join(context.args).strip()
    text, keyboard = app.search_screen(chat_id, query)
    await app.send_active(context, chat_id, text, reply_markup=keyboard)
