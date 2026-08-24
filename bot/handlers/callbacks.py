from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .commands import send_export
from ..services.organizer import build_last_screen, build_overdue_reminders_text, build_stats_text, build_today_plan
from ..views import (
    INFO,
    MAIN,
    NOTES,
    REMINDERS,
    SETTINGS,
    cancel_kb,
    data_menu,
    dayplan_menu,
    info_menu,
    main_menu,
    note_delete_confirm_kb,
    notes_archive_menu,
    notes_menu,
    quick_last_kb,
    quick_new_kb,
    reminder_delete_confirm_kb,
    reminder_edit_card_kb,
    reminder_entry_kb,
    reminder_repeat_menu,
    reminders_menu,
    settings_menu,
)

if TYPE_CHECKING:
    from ..application import BotApp


interaction_logger = logging.getLogger("bot.interactions")


async def on_button(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query and update.effective_chat
    data = query.data or ""
    if data == "menu:trainer" or data.startswith("trainer:"):
        await app.trainer.handle_callback(app, update, context)
        return
    await query.answer()
    chat_id = update.effective_chat.id
    state = app.get_chat_state(context, chat_id)

    if data.startswith("menu:"):
        state.menu = data.split(":", 1)[1]
        app.set_mode(context, chat_id, None)
        if state.menu == MAIN:
            await query.edit_message_text("Личный помощник. Напиши фразу — я сохраню заметку или напоминание.", reply_markup=main_menu())
        elif state.menu == NOTES:
            text, keyboard = app.notes_page_screen(chat_id)
            await query.edit_message_text(text, reply_markup=keyboard)
        elif state.menu == REMINDERS:
            text, keyboard = app.reminders_page_screen(chat_id)
            await query.edit_message_text(text, reply_markup=keyboard)
        elif state.menu == SETTINGS:
            settings = app.db.get_chat_settings(chat_id)
            await query.edit_message_text("⚙️ Настройки", reply_markup=settings_menu(settings.dayplan_enabled))
        elif state.menu == INFO:
            await query.edit_message_text("ℹ️ Информация", reply_markup=info_menu())
        return

    if data == "quick:new":
        app.set_mode(context, chat_id, "waiting_quick_entry")
        await query.edit_message_text(
            "Пришли одну фразу. Если есть дата или время — сделаю напоминание, иначе сохраню заметку.",
            reply_markup=quick_new_kb(),
        )
        return
    if data == "quick:today":
        await app.update_or_send_plan(context, chat_id, build_today_plan(app.db, chat_id))
        return
    if data == "quick:next":
        await query.edit_message_text(app.next_reminder_screen(chat_id), reply_markup=main_menu())
        return
    if data == "quick:overdue":
        await query.edit_message_text(build_overdue_reminders_text(app.db, chat_id), reply_markup=main_menu())
        return
    if data == "quick:tomorrow":
        await query.edit_message_text(app.tomorrow_screen(chat_id), reply_markup=main_menu())
        return
    if data == "quick:last":
        await query.edit_message_text(build_last_screen(app.db, chat_id), reply_markup=quick_last_kb())
        return
    if data == "quick:search":
        app.set_mode(context, chat_id, "waiting_search_query")
        await query.edit_message_text("Что ищем? Пришли слово или фразу.", reply_markup=cancel_kb("menu:main"))
        return
    if data == "quick:examples":
        await query.edit_message_text(
            "Примеры:\n• идея для проекта\n• 10м созвон\n• через 2 часа проверить сервер\n• завтра в 9 стоматолог\n• напомни вечером оплатить счёт",
            reply_markup=quick_new_kb(),
        )
        return

    if data == "notes:new":
        app.set_mode(context, chat_id, "waiting_note")
        await query.edit_message_text("Напиши текст заметки одним сообщением.", reply_markup=cancel_kb("menu:notes"))
        return
    if data.startswith("notes:page:"):
        text, keyboard = app.notes_page_screen(chat_id, int(data.rsplit(":", 1)[1]))
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data == "notes:archive_list":
        text, keyboard = app.notes_page_screen(chat_id, archived=True)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("notes:archive_page:"):
        text, keyboard = app.notes_page_screen(chat_id, int(data.rsplit(":", 1)[1]), archived=True)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("notes:edit_card:"):
        await app.show_note_edit_card(query, chat_id, int(data.rsplit(":", 1)[1]))
        return
    if data.startswith("notes:archive_card:"):
        await app.show_note_archive_card(query, chat_id, int(data.rsplit(":", 1)[1]))
        return
    if data.startswith("notes:edit_text:"):
        note_id = int(data.rsplit(":", 1)[1])
        note = app.db.get_note(chat_id, note_id)
        if not note:
            await query.edit_message_text("Заметка уже не существует.", reply_markup=notes_menu())
            return
        app.set_mode(context, chat_id, "waiting_note_edit_text", note_id=note_id)
        await query.edit_message_text(
            f"Текущий текст:\n\n{note.text}\n\nПришли новый текст.",
            reply_markup=cancel_kb(f"notes:edit_card:{note_id}"),
        )
        return
    if data.startswith("notes:archive:"):
        note_id = int(data.rsplit(":", 1)[1])
        if not app.db.archive_note(chat_id, note_id):
            await query.edit_message_text("Заметка уже не существует.", reply_markup=notes_menu())
            return
        interaction_logger.info("result=note_archived id=%s", note_id)
        text, keyboard = app.notes_page_screen(chat_id)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("notes:restore:"):
        note_id = int(data.rsplit(":", 1)[1])
        if not app.db.restore_note(chat_id, note_id):
            await query.edit_message_text("Заметка уже не существует.", reply_markup=notes_menu())
            return
        interaction_logger.info("result=note_restored id=%s", note_id)
        text, keyboard = app.notes_page_screen(chat_id, archived=True)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("notes:delete_confirm:"):
        note_id = int(data.rsplit(":", 1)[1])
        note = app.db.get_note(chat_id, note_id)
        await query.edit_message_text(
            "Удалить заметку без возможности восстановления?",
            reply_markup=note_delete_confirm_kb(note_id, archived=bool(note and note.is_archived)),
        )
        return
    if data.startswith("notes:delete:"):
        note_id = int(data.rsplit(":", 1)[1])
        note = app.db.get_note(chat_id, note_id)
        if not app.db.delete_note(chat_id, note_id):
            await query.edit_message_text("Заметка уже не существует.", reply_markup=notes_menu())
            return
        interaction_logger.info("result=note_deleted id=%s", note_id)
        text, keyboard = app.notes_page_screen(chat_id, archived=bool(note and note.is_archived))
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    if data == "reminders:new":
        app.set_mode(context, chat_id, "waiting_reminder")
        await query.edit_message_text(
            "Напиши напоминание одним сообщением. Например: '10м созвон' или 'завтра в 9 отчёт'.",
            reply_markup=reminder_entry_kb("menu:reminders"),
        )
        return
    if data.startswith("reminders:preset:"):
        minutes = int(data.rsplit(":", 1)[1])
        app.set_mode(context, chat_id, "waiting_preset_text", minutes=minutes)
        await query.edit_message_text(
            f"Ок. Теперь пришли текст, и я поставлю напоминание через {minutes} мин.",
            reply_markup=cancel_kb("menu:reminders"),
        )
        return
    if data.startswith("reminders:page:"):
        text, keyboard = app.reminders_page_screen(chat_id, int(data.rsplit(":", 1)[1]))
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data == "reminders:archive_list":
        text, keyboard = app.reminders_page_screen(chat_id, archived=True)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("reminders:archive_page:"):
        text, keyboard = app.reminders_page_screen(chat_id, int(data.rsplit(":", 1)[1]), archived=True)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data == "reminders:cleanup_done":
        cleaned = app.cleanup_completed_reminders(chat_id)
        text = f"✅ Убрано в архив {cleaned} завершённых напоминаний." if cleaned else "Завершённых напоминаний для очистки нет."
        _, keyboard = app.reminders_page_screen(chat_id)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("reminders:archive_card:"):
        await app.show_reminder_archive_card(query, chat_id, int(data.rsplit(":", 1)[1]))
        return
    if data.startswith("reminders:edit_card:"):
        await app.show_reminder_edit_card(query, chat_id, int(data.rsplit(":", 1)[1]))
        return
    if data.startswith("reminders:edit_text:"):
        reminder_id = int(data.rsplit(":", 1)[1])
        reminder = app.db.get_reminder(chat_id, reminder_id)
        if not reminder:
            await query.edit_message_text("Напоминание уже не существует.", reply_markup=reminders_menu())
            return
        app.set_mode(context, chat_id, "waiting_reminder_edit_text", reminder_id=reminder_id)
        await query.edit_message_text(
            f"Текущий текст:\n\n{reminder.text}\n\nПришли новый текст.",
            reply_markup=cancel_kb(f"reminders:edit_card:{reminder_id}"),
        )
        return
    if data.startswith("reminders:edit_time:"):
        reminder_id = int(data.rsplit(":", 1)[1])
        app.set_mode(context, chat_id, "waiting_reminder_edit_time", reminder_id=reminder_id)
        await query.edit_message_text(
            "Пришли новую дату или время без текста задачи. Пример: завтра в 9 или 1 февраля в 14:30",
            reply_markup=cancel_kb(f"reminders:edit_card:{reminder_id}"),
        )
        return
    if data.startswith("reminders:repeat_menu:"):
        await query.edit_message_reply_markup(reply_markup=reminder_repeat_menu(int(data.rsplit(":", 1)[1])))
        return
    if data.startswith("reminders:repeat_set:"):
        _, _, reminder_id_raw, rule = data.split(":")
        reminder_id = int(reminder_id_raw)
        if rule not in {"none", "day", "week", "month"}:
            await query.edit_message_text("Неизвестный режим повтора.", reply_markup=reminders_menu())
            return
        reminder = app.db.get_reminder(chat_id, reminder_id)
        if not reminder:
            await query.edit_message_text("Напоминание уже не существует.", reply_markup=reminders_menu())
            return
        app.db.update_reminder_repeat_rule(chat_id, reminder_id, None if rule == "none" else rule)
        interaction_logger.info("result=reminder_updated id=%s field=repeat rule=%s", reminder_id, rule)
        await query.edit_message_reply_markup(reply_markup=reminder_edit_card_kb(reminder_id))
        return
    if data.startswith("reminders:archive:"):
        reminder_id = int(data.rsplit(":", 1)[1])
        app.reminders.cancel_jobs(context.application, reminder_id)
        if not app.db.archive_reminder(chat_id, reminder_id):
            await query.edit_message_text("Напоминание уже не существует.", reply_markup=reminders_menu())
            return
        interaction_logger.info("result=reminder_archived id=%s", reminder_id)
        text, keyboard = app.reminders_page_screen(chat_id)
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("reminders:restore:"):
        reminder_id = int(data.rsplit(":", 1)[1])
        if not app.db.restore_reminder(chat_id, reminder_id):
            await query.edit_message_text("Напоминание уже не существует.", reply_markup=reminders_menu())
            return
        app.db.reopen_reminder(chat_id, reminder_id)
        app.schedule_reminder(context.application, reminder_id)
        interaction_logger.info("result=reminder_restored id=%s", reminder_id)
        await app.show_reminder_edit_card(query, chat_id, reminder_id)
        return
    if data.startswith("reminders:delete_confirm:"):
        reminder_id = int(data.rsplit(":", 1)[1])
        reminder = app.db.get_reminder(chat_id, reminder_id)
        await query.edit_message_text(
            "Удалить напоминание без возможности восстановления?",
            reply_markup=reminder_delete_confirm_kb(reminder_id, archived=bool(reminder and reminder.is_archived)),
        )
        return
    if data.startswith("reminders:delete:"):
        reminder_id = int(data.rsplit(":", 1)[1])
        reminder = app.db.get_reminder(chat_id, reminder_id)
        app.reminders.cancel_jobs(context.application, reminder_id)
        if not app.db.delete_reminder(chat_id, reminder_id):
            await query.edit_message_text("Напоминание уже не существует.", reply_markup=reminders_menu())
            return
        interaction_logger.info("result=reminder_deleted id=%s", reminder_id)
        text, keyboard = app.reminders_page_screen(chat_id, archived=bool(reminder and reminder.is_archived))
        await query.edit_message_text(text, reply_markup=keyboard)
        return
    if data.startswith("reminders:done:"):
        interaction_logger.info("action=reminder_done id=%s", data.rsplit(":", 1)[1])
        await app.complete_reminder_from_callback(query, context, chat_id, int(data.rsplit(":", 1)[1]))
        return
    if data.startswith("reminders:snooze:"):
        _, _, reminder_id_raw, minutes_raw = data.split(":")
        interaction_logger.info("action=reminder_snooze id=%s minutes=%s", reminder_id_raw, minutes_raw)
        await app.snooze_reminder_from_callback(query, context, chat_id, int(reminder_id_raw), int(minutes_raw))
        return
    if data.startswith("reminders:tomorrow:"):
        interaction_logger.info("action=reminder_tomorrow id=%s", data.rsplit(":", 1)[1])
        await app.move_reminder_to_tomorrow_from_callback(query, context, chat_id, int(data.rsplit(":", 1)[1]))
        return

    if data == "settings:tz":
        app.set_mode(context, chat_id, "waiting_tz")
        await query.edit_message_text("Пришли смещение от UTC. Пример: +3, -5, +3:30", reply_markup=cancel_kb("menu:settings"))
        return
    if data == "settings:dayplan_menu":
        settings = app.db.get_chat_settings(chat_id)
        await query.edit_message_text("Настройки плана дня", reply_markup=dayplan_menu(settings.dayplan_enabled))
        return
    if data == "settings:dayplan_toggle":
        await app.toggle_dayplan(query, context, chat_id)
        return
    if data == "settings:dayplan_time":
        app.set_mode(context, chat_id, "waiting_dayplan_time")
        await query.edit_message_text("Пришли время в формате HH:MM, например 08:00", reply_markup=cancel_kb("settings:dayplan_menu"))
        return
    if data == "settings:data_menu":
        await query.edit_message_text("💾 Резервная копия", reply_markup=data_menu())
        return
    if data == "settings:export":
        await send_export(app, context, chat_id)
        return
    if data == "settings:import":
        app.set_mode(context, chat_id, "waiting_import")
        await query.edit_message_text("Пришли JSON-файл экспорта документом.", reply_markup=cancel_kb("settings:data_menu"))
        return
    if data == "settings:stats":
        settings = app.db.get_chat_settings(chat_id)
        await query.edit_message_text(build_stats_text(app.db, chat_id), reply_markup=settings_menu(settings.dayplan_enabled))
        return

    if data == "info:id":
        await query.edit_message_text(f"user_id: {update.effective_user.id}\nchat_id: {chat_id}", reply_markup=info_menu())
        return
    if data == "info:stats":
        await query.edit_message_text(build_stats_text(app.db, chat_id), reply_markup=info_menu())
        return
    if data.startswith("search:repeat:"):
        query_text = data.split(":", 2)[2]
        text, keyboard = app.search_screen(chat_id, query_text)
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    await query.edit_message_text("Это действие уже устарело или не существует.", reply_markup=main_menu())
