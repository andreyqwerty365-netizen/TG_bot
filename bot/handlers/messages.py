from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from ..services.import_export import MAX_IMPORT_FILE_BYTES, import_payload
from ..services.organizer import (
    build_capture_success_text,
    build_saved_reminder_text,
    create_preset_reminder,
    create_reminder_from_text,
    format_quick_reminder_confirmation,
    is_valid_hhmm,
    parse_tz_offset,
    parse_when_text,
    smart_capture,
)
from ..utils.date_utils import fmt_ru_date_or_time, local_to_utc
from ..views import cancel_kb, main_menu, reminder_created_kb, reminder_entry_kb, routine_settings_menu, routine_task_policy_menu, routine_task_shift_menu, settings_menu

if TYPE_CHECKING:
    from ..application import BotApp


interaction_logger = logging.getLogger("bot.interactions")


async def capture_text(app: "BotApp", context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    result = smart_capture(app.db, chat_id, text)
    if result.kind == "reminder":
        app.schedule_reminder(context.application, result.reminder_id)
        settings = app.db.get_chat_settings(chat_id)
        interaction_logger.info(
            "result=reminder id=%s chars=%s",
            result.reminder_id,
            len(result.text),
        )
        await app.send_active(
            context,
            chat_id,
            build_capture_success_text(result.remind_at_utc, settings.tz_offset_minutes, result.text),
            reply_markup=reminder_created_kb(result.reminder_id),
        )
        return
    interaction_logger.info("result=note id=%s chars=%s", result.note_id, len(result.text))
    await app.send_active(context, chat_id, "✅ Сохранил как заметку.", reply_markup=main_menu())


async def on_text(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state = app.get_chat_state(context, chat_id)
    text = (update.message.text or "").strip()
    if not text:
        await app.send_active(context, chat_id, "Пустой текст не сохраняю.", reply_markup=main_menu())
        return

    if state.mode and state.mode.startswith("trainer_"):
        if await app.trainer.handle_text(app, update, context):
            return

    if state.mode == "waiting_routine_task_text":
        app.set_mode(context, chat_id, "routine_add_shift", text=text)
        await app.send_active(context, chat_id, "Для каких дней эта задача?", reply_markup=routine_task_shift_menu())
        return
    if state.mode == "waiting_routine_task_offset":
        try:
            minutes = int(text)
        except ValueError:
            minutes = -1
        if not 0 <= minutes <= 1440:
            await app.send_active(context, chat_id, "Введи число минут от 0 до 1440.", reply_markup=cancel_kb("routine:tasks"))
            return
        state.mode = "routine_add_policy"
        state.payload["offset_minutes"] = minutes
        await app.send_active(context, chat_id, "Повторять задачу в сводках?", reply_markup=routine_task_policy_menu())
        return
    if state.mode == "waiting_routine_wake_time":
        if not is_valid_hhmm(text):
            await app.send_active(context, chat_id, "Нужен формат HH:MM.", reply_markup=cancel_kb("routine:settings"))
            return
        app.db.set_shift_wake_time(chat_id, state.payload["shift_type"], text)
        app.set_mode(context, chat_id, None)
        routine = app.db.get_routine_settings(chat_id)
        await app.send_active(context, chat_id, "✅ Время подъёма обновлено.", reply_markup=routine_settings_menu(routine.enabled, routine.digest_interval_hours, app.db.get_shift_wake_times(chat_id)))
        return

    if state.mode == "waiting_import":
        await app.send_active(context, chat_id, "Я жду JSON-документ, а не текст.", reply_markup=main_menu())
        return
    if state.mode == "waiting_note":
        note_id = app.db.add_note(chat_id, text)
        interaction_logger.info("result=note id=%s mode=waiting_note chars=%s", note_id, len(text))
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, "✅ Заметка сохранена.", reply_markup=main_menu())
        return
    if state.mode == "waiting_search_query":
        app.set_mode(context, chat_id, None)
        result_text, keyboard = app.search_screen(chat_id, text)
        await app.send_active(context, chat_id, result_text, reply_markup=keyboard)
        return
    if state.mode == "waiting_preset_text":
        minutes = int(state.payload["minutes"])
        result = create_preset_reminder(app.db, chat_id, text, minutes)
        app.schedule_reminder(context.application, result.reminder_id)
        interaction_logger.info("result=reminder id=%s preset_minutes=%s chars=%s", result.reminder_id, minutes, len(text))
        app.set_mode(context, chat_id, None)
        settings = app.db.get_chat_settings(chat_id)
        await app.send_active(
            context,
            chat_id,
            format_quick_reminder_confirmation(result.remind_at_utc, settings.tz_offset_minutes, text),
            reply_markup=reminder_created_kb(result.reminder_id),
        )
        return
    if state.mode == "waiting_reminder":
        parsed, remind_at_utc = create_reminder_from_text(app.db, chat_id, text)
        if not parsed or remind_at_utc is None:
            await app.send_active(
                context,
                chat_id,
                "Не понял время. Пример: '10м созвон' или 'завтра в 9 отчёт'.",
                reply_markup=reminder_entry_kb("menu:reminders"),
            )
            return
        reminder_id = app.db.add_reminder(chat_id, parsed.text, remind_at_utc, parsed.repeat_rule)
        app.schedule_reminder(context.application, reminder_id)
        interaction_logger.info("result=reminder id=%s mode=waiting_reminder chars=%s", reminder_id, len(parsed.text))
        app.set_mode(context, chat_id, None)
        settings = app.db.get_chat_settings(chat_id)
        await app.send_active(
            context,
            chat_id,
            build_saved_reminder_text(parsed, remind_at_utc, settings.tz_offset_minutes),
            reply_markup=reminder_created_kb(reminder_id),
        )
        return
    if state.mode == "waiting_quick_entry":
        app.set_mode(context, chat_id, None)
        await capture_text(app, context, chat_id, text)
        return
    if state.mode == "waiting_reminder_edit_text":
        reminder_id = int(state.payload["reminder_id"])
        if not app.db.update_reminder_text(chat_id, reminder_id, text):
            await app.send_active(context, chat_id, "Напоминание уже не существует.", reply_markup=main_menu())
            return
        interaction_logger.info("result=reminder_updated id=%s field=text chars=%s", reminder_id, len(text))
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, "✅ Текст напоминания обновлён.", reply_markup=main_menu())
        return
    if state.mode == "waiting_note_edit_text":
        note_id = int(state.payload["note_id"])
        if not app.db.update_note(chat_id, note_id, text):
            await app.send_active(context, chat_id, "Заметка уже не существует.", reply_markup=main_menu())
            return
        interaction_logger.info("result=note_updated id=%s chars=%s", note_id, len(text))
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, "✅ Заметка обновлена.", reply_markup=main_menu())
        return
    if state.mode == "waiting_reminder_edit_time":
        reminder_id = int(state.payload["reminder_id"])
        parsed_when = parse_when_text(app.db, chat_id, text)
        if not parsed_when:
            await app.send_active(
                context,
                chat_id,
                "Не распознал время. Пример: завтра в 9 или 1 февраля в 14:30",
                reply_markup=cancel_kb(f"reminders:edit_card:{reminder_id}"),
            )
            return
        tz_offset = app.db.get_chat_settings(chat_id).tz_offset_minutes
        remind_at = local_to_utc(parsed_when, tz_offset)
        app.db.update_reminder_time(chat_id, reminder_id, remind_at)
        app.schedule_reminder(context.application, reminder_id)
        interaction_logger.info("result=reminder_updated id=%s field=time", reminder_id)
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, f"✅ Время обновлено: {fmt_ru_date_or_time(remind_at, tz_offset)}", reply_markup=main_menu())
        return
    if state.mode == "waiting_tz":
        offset = parse_tz_offset(text)
        if offset is None:
            await app.send_active(context, chat_id, "Нужен формат +3, -5 или +3:30", reply_markup=cancel_kb("menu:settings"))
            return
        app.db.set_timezone(chat_id, offset)
        settings = app.db.get_chat_settings(chat_id)
        app.sync_dayplan_schedule(context.application, chat_id)
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, f"✅ Таймзона обновлена: UTC{text}", reply_markup=settings_menu(settings.dayplan_enabled))
        return
    if state.mode == "waiting_dayplan_time":
        if not is_valid_hhmm(text):
            await app.send_active(context, chat_id, "Нужен формат HH:MM, например 08:00", reply_markup=cancel_kb("settings:dayplan_menu"))
            return
        settings = app.db.get_chat_settings(chat_id)
        app.db.set_dayplan(chat_id, settings.dayplan_enabled, text)
        app.sync_dayplan_schedule(context.application, chat_id)
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, f"✅ Время плана дня обновлено: {text}", reply_markup=settings_menu(settings.dayplan_enabled))
        return

    await capture_text(app, context, chat_id, text)


async def on_voice(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await app.send_active(
        context,
        chat_id,
        "Голосовой ввод добавим следующим этапом. Пока пришли мысль текстом — я сохраню заметку или напоминание.",
        reply_markup=main_menu(),
    )


async def on_document(app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state = app.get_chat_state(context, chat_id)
    if state.mode != "waiting_import":
        await app.send_active(context, chat_id, "Файл получил, но импорт сейчас не ожидается. Если нужен импорт — /import.", reply_markup=main_menu())
        return

    document = update.message.document
    if not document or not (document.file_name or "").lower().endswith(".json"):
        await app.send_active(context, chat_id, "Нужен JSON-файл.", reply_markup=main_menu())
        return
    if document.file_size is not None and document.file_size > MAX_IMPORT_FILE_BYTES:
        await app.send_active(context, chat_id, "JSON-файл слишком большой. Максимум: 5 МБ.", reply_markup=main_menu())
        return

    try:
        telegram_file = await context.bot.get_file(document.file_id)
        data = await telegram_file.download_as_bytearray()
        if len(data) > MAX_IMPORT_FILE_BYTES:
            raise ValueError("JSON-файл слишком большой. Максимум: 5 МБ.")
        payload = json.loads(bytes(data).decode("utf-8"))
    except Exception as exc:
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, f"Не смог прочитать JSON: {exc}", reply_markup=main_menu())
        return

    try:
        result = import_payload(app.db, chat_id, payload)
        for reminder_id in result.scheduled_reminder_ids:
            app.schedule_reminder(context.application, reminder_id)
        app.sync_dayplan_schedule(context.application, chat_id)
    except Exception as exc:
        app.set_mode(context, chat_id, None)
        await app.send_active(context, chat_id, f"Ошибка импорта: {exc}", reply_markup=main_menu())
        return

    app.set_mode(context, chat_id, None)
    await app.send_active(
        context,
        chat_id,
        (
            "✅ Импорт завершён.\n"
            f"Заметки: +{result.imported_notes} активных / +{result.imported_archived_notes} архивных\n"
            f"Напоминания: +{result.imported_reminders} активных / +{result.imported_archived_reminders} архивных\n"
            f"Пропущено дублей: {result.skipped_duplicates}"
        ),
        reply_markup=main_menu(),
    )
