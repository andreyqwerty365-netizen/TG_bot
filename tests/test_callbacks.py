from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.application import ACTIVE_KEY, PLAN_KEY, STATE_KEY, BotApp
from bot.config import Settings
from bot.handlers.callbacks import on_button


class FakeJob:
    def __init__(self) -> None:
        self.removed = False

    def schedule_removal(self) -> None:
        self.removed = True


class FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, list[FakeJob]] = {}
        self.once_calls: list[dict] = []

    def get_jobs_by_name(self, name: str):
        return self.jobs.get(name, [])

    def run_once(self, callback, when, data, name):
        self.once_calls.append({"callback": callback, "when": when, "data": data, "name": name})


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
