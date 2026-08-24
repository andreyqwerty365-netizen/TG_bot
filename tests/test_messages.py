from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.application import ACTIVE_KEY, PLAN_KEY, STATE_KEY, BotApp
from bot.config import Settings
from bot.handlers.messages import on_document
from bot.services.import_export import MAX_IMPORT_FILE_BYTES


def build_runtime(tmp_path: Path):
    app = BotApp(Settings(bot_token="123:token", db_path=tmp_path / "notes.db"))
    app.db.init()
    bot = SimpleNamespace(
        delete_message=AsyncMock(),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        get_file=AsyncMock(),
    )
    application = SimpleNamespace(
        bot_data={
            STATE_KEY: {},
            ACTIVE_KEY: {},
            PLAN_KEY: {},
        },
        job_queue=SimpleNamespace(get_jobs_by_name=lambda name: []),
    )
    context = SimpleNamespace(application=application, bot=bot)
    return app, context


@pytest.mark.anyio
async def test_import_rejects_oversized_document_before_download(tmp_path: Path):
    app, context = build_runtime(tmp_path)
    app.set_mode(context, 1, "waiting_import")
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=SimpleNamespace(
            document=SimpleNamespace(
                file_name="backup.json",
                file_id="file-id",
                file_size=MAX_IMPORT_FILE_BYTES + 1,
            )
        ),
    )

    await on_document(app, update, context)

    context.bot.get_file.assert_not_awaited()
    assert "слишком большой" in context.bot.send_message.await_args.args[1]
