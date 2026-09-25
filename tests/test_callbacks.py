from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw

from bot.application import ACTIVE_KEY, PLAN_KEY, STATE_KEY, BotApp
from bot.config import Settings
from bot.handlers.callbacks import on_button
from bot.handlers.messages import on_photo, on_text
from bot.services.routines import due_one_time_tasks


class FakeJob:
    def __init__(self) -> None:
        self.removed = False

    def schedule_removal(self) -> None:
        self.removed = True


class FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, list[FakeJob]] = {}
        self.once_calls: list[dict] = []
        self.repeat_calls: list[dict] = []

    def get_jobs_by_name(self, name: str):
        return self.jobs.get(name, [])

    def run_once(self, callback, when, data, name):
        self.once_calls.append({"callback": callback, "when": when, "data": data, "name": name})

    def run_repeating(self, callback, interval, first, data, name):
        self.repeat_calls.append({"callback": callback, "interval": interval, "first": first, "data": data, "name": name})


def build_runtime(tmp_path: Path):
    app = BotApp(Settings(bot_token="123:token", db_path=tmp_path / "notes.db"))
    app.db.init()
    bot = SimpleNamespace(
        delete_message=AsyncMock(),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        send_document=AsyncMock(),
    )
    application = SimpleNamespace(
        bot_data={
            STATE_KEY: {},
            ACTIVE_KEY: {},
            PLAN_KEY: {},
        },
        job_queue=FakeJobQueue(),
        bot=bot,
    )
    return app, SimpleNamespace(application=application, bot=bot)


async def press(app: BotApp, context, data: str):
    query = SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=1),
    )
    await on_button(app, update, context)
    query.answer.assert_awaited_once()
    return query


@pytest.mark.anyio
async def test_stale_menu_callback_is_rejected_without_execution(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    note_id = app.db.add_note(1, "Не архивировать")
    app.db.set_active_message_id(1, 200)
    query = SimpleNamespace(
        data=f"notes:archive:{note_id}",
        message=SimpleNamespace(message_id=199),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=1),
    )

    await on_button(app, update, context)

    query.answer.assert_awaited_once_with(
        "Это меню устарело. Используй последнее сообщение бота.",
        show_alert=True,
    )
    query.edit_message_text.assert_not_awaited()
    assert app.db.get_note(1, note_id).is_archived is False


@pytest.mark.anyio
async def test_routine_schedule_and_task_constructor(tmp_path: Path):
    app, context = build_runtime(tmp_path)

    await press(app, context, "routine:set_shift:2026-09-02:night")
    assert app.db.get_shift_day(1, datetime(2026, 9, 2).date()).shift_type == "night"

    await press(app, context, "routine:add")
    assert app.get_chat_state(context, 1).mode == "waiting_routine_task_text"

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=SimpleNamespace(text="Выпить стакан воды"),
    )
    await on_text(app, update, context)
    assert app.get_chat_state(context, 1).mode == "routine_add_shift"

    await press(app, context, "routine:add_shift:all")
    await press(app, context, "routine:add_offset:0")
    await press(app, context, "routine:add_policy:once")

    task = app.db.list_routine_tasks(1)[0]
    assert task.text == "Выпить стакан воды"
    assert task.repeat_in_digest is False


@pytest.mark.anyio
async def test_start_day_uses_scheduled_shift_and_current_click_time(tmp_path: Path, monkeypatch):
    app, context = build_runtime(tmp_path)
    app.db.set_shift_day(1, datetime(2026, 9, 2).date(), "night")
    app.db.add_routine_task(1, "Выпить воды", "all", 0, False, 60)
    clicked_at = datetime(2026, 9, 2, 14, 23, tzinfo=UTC)
    monkeypatch.setattr("bot.handlers.callbacks.utc_now", lambda: clicked_at)

    query = await press(app, context, "routine:start")

    started = app.db.get_latest_routine_day_start(1)
    assert started is not None
    assert started.routine_date == datetime(2026, 9, 2).date()
    assert started.shift_type == "night"
    assert started.started_at == clicked_at
    assert app.db.get_routine_settings(1).enabled is True
    assert "День начат" in query.edit_message_text.await_args.args[0]
    assert due_one_time_tasks(app.db, 1, clicked_at) == []


@pytest.mark.anyio
async def test_end_day_callback_closes_active_routine(tmp_path: Path, monkeypatch):
    app, context = build_runtime(tmp_path)
    started_at = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
    ended_at = datetime(2026, 9, 2, 23, 0, tzinfo=UTC)
    app.db.start_routine_day(1, started_at.date(), "off", started_at)
    monkeypatch.setattr("bot.handlers.callbacks.utc_now", lambda: ended_at)

    query = await press(app, context, "routine:end")

    assert app.db.get_latest_routine_day_start(1).ended_at == ended_at
    assert "День завершён" in query.edit_message_text.await_args.args[0]


@pytest.mark.anyio
async def test_schedule_import_confirmation_applies_whole_month(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    state = app.get_chat_state(context, 1)
    state.mode = "routine_schedule_confirm"
    state.payload = {"schedule_year": 2026, "schedule_month": 9, "schedule_shifts": ["day", "night"] + ["off"] * 28}

    await press(app, context, "routine:confirm_schedule")

    assert app.db.get_shift_day(1, datetime(2026, 9, 1).date()).shift_type == "day"
    assert app.db.get_shift_day(1, datetime(2026, 9, 2).date()).shift_type == "night"
    assert app.db.get_shift_day(1, datetime(2026, 9, 30).date()).shift_type == "off"


@pytest.mark.anyio
async def test_schedule_import_collects_month_then_photo_preview(tmp_path: Path):
    app, context = build_runtime(tmp_path)

    await press(app, context, "routine:import_schedule")
    assert app.get_chat_state(context, 1).mode == "waiting_schedule_month"

    text_update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=SimpleNamespace(text="09.2026"),
    )
    await on_text(app, text_update, context)
    assert app.get_chat_state(context, 1).mode == "waiting_schedule_image"

    image = Image.new("RGB", (20 + 30 * 12 + 20, 50), "white")
    draw = ImageDraw.Draw(image)
    for index in range(31):
        x = 20 + index * 12
        draw.line((x, 0, x, 49), fill="black", width=1)
    draw.rectangle((21, 30, 31, 48), fill="red")
    draw.rectangle((33, 30, 43, 48), fill="blue")
    output = BytesIO()
    image.save(output, format="PNG")
    telegram_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(output.getvalue())))
    context.bot.get_file = AsyncMock(return_value=telegram_file)
    photo_update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=SimpleNamespace(photo=[SimpleNamespace(file_id="photo", file_size=len(output.getvalue()))]),
    )

    await on_photo(app, photo_update, context)

    state = app.get_chat_state(context, 1)
    assert state.mode == "routine_schedule_confirm"
    assert state.payload["schedule_shifts"][:3] == ["day", "night", "off"]
    assert "Дневные: 1" in context.bot.send_message.await_args.args[1]


@pytest.mark.anyio
async def test_routine_done_callback_marks_current_routine_day(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    task_id = app.db.add_routine_task(1, "Задача", "all", 0, True, 960)

    await press(app, context, f"routine:done:{task_id}:2026-09-02")

    assert app.db.get_routine_task_statuses(1, datetime(2026, 9, 2).date())[task_id] == "done"


@pytest.mark.anyio
async def test_today_button_reuses_the_current_menu_message(tmp_path: Path):
    app, context = build_runtime(tmp_path)

    query = await press(app, context, "quick:today")

    query.edit_message_text.assert_awaited_once()
    context.bot.send_message.assert_not_awaited()


@pytest.mark.anyio
async def test_note_callbacks_archive_restore_and_delete(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    note_id = app.db.add_note(1, "Тестовая заметка")

    await press(app, context, f"notes:archive:{note_id}")
    assert app.db.get_note(1, note_id).is_archived

    await press(app, context, f"notes:restore:{note_id}")
    assert not app.db.get_note(1, note_id).is_archived

    confirm = await press(app, context, f"notes:delete_confirm:{note_id}")
    callbacks = [button.callback_data for row in confirm.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard for button in row]
    assert f"notes:delete:{note_id}" in callbacks

    await press(app, context, f"notes:delete:{note_id}")
    assert app.db.get_note(1, note_id) is None


@pytest.mark.anyio
async def test_note_page_callback_opens_second_page(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    for idx in range(12):
        app.db.add_note(1, f"Заметка {idx}")

    query = await press(app, context, "notes:page:1")

    assert "Страница 2 из 2" in query.edit_message_text.await_args.args[0]


@pytest.mark.anyio
async def test_reminder_callbacks_archive_restore_and_delete(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    reminder_id = app.db.add_reminder(1, "Тестовое напоминание", datetime(2030, 1, 1, 12, 0, tzinfo=UTC))
    context.application.job_queue.jobs[f"reminder:{reminder_id}"] = [FakeJob()]

    await press(app, context, f"reminders:archive:{reminder_id}")
    assert app.db.get_reminder(1, reminder_id).is_archived
    assert context.application.job_queue.jobs[f"reminder:{reminder_id}"][0].removed

    await press(app, context, f"reminders:restore:{reminder_id}")
    restored = app.db.get_reminder(1, reminder_id)
    assert restored is not None and not restored.is_archived and restored.done_at is None
    assert any(call["name"] == f"reminder:{reminder_id}" for call in context.application.job_queue.once_calls)

    await press(app, context, f"reminders:delete:{reminder_id}")
    assert app.db.get_reminder(1, reminder_id) is None


@pytest.mark.anyio
async def test_settings_callbacks_start_import_and_send_export(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    app.db.add_note(1, "Экспортируемая заметка")

    await press(app, context, "settings:import")
    assert app.get_chat_state(context, 1).mode == "waiting_import"

    await press(app, context, "settings:export")
    context.bot.send_document.assert_awaited_once()
    assert context.bot.send_document.await_args.kwargs["chat_id"] == 1
    assert context.bot.send_document.await_args.kwargs["document"].name == "telegram-assistant-export.json"


@pytest.mark.anyio
async def test_reminder_callback_rejects_unknown_repeat_rule(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    reminder_id = app.db.add_reminder(1, "Тест", datetime(2030, 1, 1, 12, 0, tzinfo=UTC))

    query = await press(app, context, f"reminders:repeat_set:{reminder_id}:hour")

    reminder = app.db.get_reminder(1, reminder_id)
    assert reminder is not None and reminder.repeat_rule is None
    assert "Неизвестный режим повтора" in query.edit_message_text.await_args.args[0]
