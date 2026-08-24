from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

from bot.application import BotApp, create_application, safe_callback_label
from bot.config import Settings


class FakeJob:
    def __init__(self) -> None:
        self.removed = False

    def schedule_removal(self) -> None:
        self.removed = True


class FakeJobQueue:
    def __init__(self) -> None:
        self.once_calls: list[dict] = []
        self.repeat_calls: list[dict] = []
        self.jobs: dict[str, list[FakeJob]] = {}

    def get_jobs_by_name(self, name: str):
        return self.jobs.get(name, [])

    def run_once(self, callback, when, data, name):
        self.once_calls.append({"callback": callback, "when": when, "data": data, "name": name})

    def run_repeating(self, callback, interval, first, data, name):
        self.repeat_calls.append({"callback": callback, "interval": interval, "first": first, "data": data, "name": name})


class FakeApplication:
    def __init__(self) -> None:
        self.job_queue = FakeJobQueue()
        self.bot = SimpleNamespace(set_my_commands=AsyncMock(return_value=True))


def test_create_application_requires_token(tmp_path: Path):
    settings = Settings(bot_token="", db_path=tmp_path / "notes.db")
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        create_application(settings)


def test_create_application_requires_owner_allowlist(tmp_path: Path):
    settings = Settings(bot_token="123:token", db_path=tmp_path / "notes.db")
    with pytest.raises(RuntimeError, match="BOT_ALLOWED_USER_IDS"):
        create_application(settings)


def test_settings_from_env_parses_allowed_user_ids(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:token")
    monkeypatch.setenv("BOT_ALLOWED_USER_IDS", "111, 222;333")
    settings = Settings.from_env()

    assert settings.allowed_user_ids == frozenset({111, 222, 333})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BOT_LOG_MAX_BYTES", "0"),
        ("BOT_LOG_BACKUP_COUNT", "-1"),
        ("BOT_DEFAULT_TZ_MINUTES", "841"),
    ],
)
def test_settings_from_env_rejects_invalid_numeric_values(monkeypatch, name: str, value: str):
    monkeypatch.setenv("BOT_TOKEN", "123:token")
    monkeypatch.setenv("BOT_ALLOWED_USER_IDS", "111")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_settings_from_env_rejects_invalid_owner_id(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:token")
    monkeypatch.setenv("BOT_ALLOWED_USER_IDS", "owner")

    with pytest.raises(ValueError, match="BOT_ALLOWED_USER_IDS"):
        Settings.from_env()


def test_settings_from_env_rejects_shared_log_path(monkeypatch, tmp_path: Path):
    shared_log = str(tmp_path / "shared.log")
    monkeypatch.setenv("BOT_TOKEN", "123:token")
    monkeypatch.setenv("BOT_ALLOWED_USER_IDS", "111")
    monkeypatch.setenv("BOT_LOG_PATH", shared_log)
    monkeypatch.setenv("BOT_INTERACTION_LOG_PATH", shared_log)

    with pytest.raises(ValueError, match="разные файлы"):
        Settings.from_env()


def test_owner_allowlist_accepts_only_configured_user(tmp_path: Path):
    settings = Settings(bot_token="123:token", db_path=tmp_path / "notes.db", allowed_user_ids=frozenset({111}))
    bot_app = BotApp(settings)

    assert bot_app.is_user_allowed(111)
    assert not bot_app.is_user_allowed(222)
    assert not bot_app.is_user_allowed(None)


def test_empty_owner_allowlist_denies_access(tmp_path: Path):
    bot_app = BotApp(Settings(bot_token="123:token", db_path=tmp_path / "notes.db"))

    assert not bot_app.is_user_allowed(111)
    assert not bot_app.is_user_allowed(None)


def test_default_timezone_is_used_for_new_chat(tmp_path: Path):
    settings = Settings(bot_token="123:token", db_path=tmp_path / "notes.db", default_tz_offset_minutes=180)
    bot_app = BotApp(settings)
    bot_app.db.init()

    assert bot_app.db.get_chat_settings(111).tz_offset_minutes == 180

    bot_app.db.set_dayplan(222, True, "08:00")
    assert bot_app.db.get_chat_settings(222).tz_offset_minutes == 180


def test_callback_log_label_redacts_free_text():
    assert safe_callback_label("reminders:snooze:12:10") == "reminders:snooze:12:10"
    assert safe_callback_label("search:repeat:личный запрос") == "search:repeat:<redacted>"


@pytest.mark.anyio
async def test_owner_allowlist_stops_unauthorized_updates(tmp_path: Path):
    settings = Settings(bot_token="123:token", db_path=tmp_path / "notes.db", allowed_user_ids=frozenset({111}))
    bot_app = BotApp(settings)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=222), callback_query=None, effective_chat=None)

    with pytest.raises(ApplicationHandlerStop):
        await bot_app.require_allowed_user(update, SimpleNamespace())


def test_create_application_builds_with_valid_token(tmp_path: Path):
    settings = Settings(bot_token="123:token", db_path=tmp_path / "notes.db", allowed_user_ids=frozenset({111}))
    app = create_application(settings)
    assert app is not None


@pytest.mark.anyio
async def test_interaction_log_omits_telegram_identifiers(tmp_path: Path, caplog):
    bot_app = BotApp(Settings(bot_token="123:token", db_path=tmp_path / "notes.db"))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"chat_states": {}}))
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=987654321),
        effective_user=SimpleNamespace(id=123456789),
        callback_query=None,
        message=SimpleNamespace(text="Личный текст", voice=None, document=None),
    )

    with caplog.at_level("INFO", logger="bot.interactions"):
        await bot_app.log_update(update, context)

    message = caplog.records[-1].getMessage()
    assert "123456789" not in message
    assert "987654321" not in message
    assert "Личный текст" not in message
    assert "event=text chars=12" in message


@pytest.mark.anyio
async def test_post_init_restores_pending_reminders_and_dayplan(tmp_path: Path):
    settings = Settings(bot_token="123:token", db_path=tmp_path / "notes.db")
    bot_app = BotApp(settings)
    bot_app.db.init()

    bot_app.db.add_reminder(1, "Созвон", datetime(2026, 2, 1, 9, 0, tzinfo=UTC))
    bot_app.db.set_timezone(1, 180)
    bot_app.db.set_dayplan(1, True, "08:00")

    fake_application = FakeApplication()
    await bot_app.post_init(fake_application)

    assert len(fake_application.job_queue.once_calls) == 1
    assert fake_application.job_queue.once_calls[0]["name"].startswith("reminder:")
    assert len(fake_application.job_queue.repeat_calls) == 1
    assert fake_application.job_queue.repeat_calls[0]["name"] == "dayplan:1"


@pytest.mark.anyio
async def test_fire_reminder_schedules_one_retry_even_if_delivery_fails(tmp_path: Path):
    settings = Settings(bot_token="123:token", db_path=tmp_path / "notes.db")
    bot_app = BotApp(settings)
    bot_app.db.init()
    reminder_id = bot_app.db.add_reminder(1, "Созвон", datetime(2026, 2, 1, 9, 0, tzinfo=UTC))
    bot_app._send_reminder_notification = AsyncMock(side_effect=RuntimeError("network down"))
    fake_application = FakeApplication()
    context = SimpleNamespace(application=fake_application, job=SimpleNamespace(data={"chat_id": 1, "reminder_id": reminder_id}))

    with pytest.raises(RuntimeError, match="network down"):
        await bot_app.fire_reminder_job(context)

    retry_calls = [call for call in fake_application.job_queue.once_calls if call["name"] == f"retry10:{reminder_id}"]
    assert len(retry_calls) == 1


def test_sync_dayplan_schedule_removes_job_when_disabled(tmp_path: Path):
    bot_app = BotApp(Settings(bot_token="123:token", db_path=tmp_path / "notes.db"))
    bot_app.db.init()
    bot_app.db.set_dayplan(1, False, "08:00")
    fake_application = FakeApplication()
    stale_job = FakeJob()
    fake_application.job_queue.jobs["dayplan:1"] = [stale_job]

    bot_app.sync_dayplan_schedule(fake_application, 1)

    assert stale_job.removed
    assert fake_application.job_queue.repeat_calls == []


def test_sync_dayplan_schedule_registers_enabled_job(tmp_path: Path):
    bot_app = BotApp(Settings(bot_token="123:token", db_path=tmp_path / "notes.db"))
    bot_app.db.init()
    bot_app.db.set_timezone(1, 180)
    bot_app.db.set_dayplan(1, True, "08:00")
    fake_application = FakeApplication()

    bot_app.sync_dayplan_schedule(fake_application, 1)

    assert len(fake_application.job_queue.repeat_calls) == 1
    assert fake_application.job_queue.repeat_calls[0]["name"] == "dayplan:1"
