from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.application import ACTIVE_KEY, PLAN_KEY, STATE_KEY, BotApp
from bot.config import Settings
from bot.handlers.callbacks import on_button
from bot.handlers.messages import on_text
from bot.views import main_menu


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_trainer_module(name: str):
    full_name = f"bot.trainer.{name}"
    assert importlib.util.find_spec(full_name) is not None, f"Missing trainer module: {full_name}"
    return importlib.import_module(full_name)


def callback_values(markup) -> set[str]:
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_secretary_main_menu_opens_trainer_as_separate_section() -> None:
    assert "menu:trainer" in callback_values(main_menu())


def test_trainer_keyboards_use_namespaced_callbacks() -> None:
    views = load_trainer_module("views")
    callbacks = callback_values(views.trainer_main_menu())

    assert "trainer:workout" in callbacks
    assert "trainer:history" in callbacks
    assert "trainer:export" in callbacks
    assert "menu:main" in callbacks
    assert all(value == "menu:main" or value.startswith("trainer:") for value in callbacks)


def test_combined_requirements_drop_aiogram_and_include_excel_export() -> None:
    requirements = (PROJECT_DIR / "requirements.txt").read_text(encoding="utf-8").lower()

    assert "aiogram" not in requirements
    assert "openpyxl" in requirements
    assert "tzdata" in requirements


def test_environment_example_documents_trainer_storage_and_timezone() -> None:
    example = (PROJECT_DIR / ".env.example").read_text(encoding="utf-8")

    assert "BOT_TRAINER_DB_PATH=workouts.sqlite3" in example
    assert "BOT_EXERCISES_PATH=exercises.json" in example
    assert "BOT_TRAINER_TIMEZONE=Europe/Moscow" in example


def build_runtime(tmp_path: Path):
    settings = Settings(
        bot_token="123:token",
        db_path=tmp_path / "notes.db",
        allowed_user_ids=frozenset({1}),
    )
    app = BotApp(settings)
    app.db.init()
    bot = SimpleNamespace(
        delete_message=AsyncMock(),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        send_document=AsyncMock(),
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=100)),
    )
    application = SimpleNamespace(
        bot_data={STATE_KEY: {}, ACTIVE_KEY: {}, PLAN_KEY: {}},
        bot=bot,
        job_queue=SimpleNamespace(get_jobs_by_name=lambda name: []),
    )
    return app, SimpleNamespace(application=application, bot=bot, args=[])


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
        effective_user=SimpleNamespace(id=1, username="tester", full_name="Test User"),
    )
    await on_button(app, update, context)
    query.answer.assert_awaited_once()
    return query


@pytest.mark.anyio
async def test_trainer_menu_is_routed_before_secretary_fallback(tmp_path: Path) -> None:
    app, context = build_runtime(tmp_path)

    query = await press(app, context, "menu:trainer")

    assert "Персональный тренер" in query.edit_message_text.await_args.args[0]


@pytest.mark.anyio
async def test_strength_workout_flow_uses_shared_chat_state_and_separate_database(tmp_path: Path) -> None:
    app, context = build_runtime(tmp_path)

    await press(app, context, "trainer:workout")
    await press(app, context, "trainer:group:legs")
    await press(app, context, "trainer:exercise:squat")
    await press(app, context, "trainer:sets:1")
    assert app.get_chat_state(context, 1).mode == "trainer_base_weight"

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=1, username="tester", full_name="Test User"),
        message=SimpleNamespace(text="40"),
    )
    await on_text(app, update, context)
    assert app.get_chat_state(context, 1).mode == "trainer_editing_weights"

    await press(app, context, "trainer:save")
    history = app.trainer_database.get_recent_workouts(1)
    assert len(history) == 1
    assert history[0].exercise_name == "Приседания со штангой"
    assert history[0].weights == (40.0,)


@pytest.mark.anyio
async def test_cardio_distance_flow_is_handled_as_trainer_text(tmp_path: Path) -> None:
    app, context = build_runtime(tmp_path)

    await press(app, context, "trainer:workout")
    await press(app, context, "trainer:group:cardio")
    await press(app, context, "trainer:exercise:treadmill_walking")
    assert app.get_chat_state(context, 1).mode == "trainer_distance"

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=1, username="tester", full_name="Test User"),
        message=SimpleNamespace(text="2,4"),
    )
    await on_text(app, update, context)

    history = app.trainer_database.get_recent_workouts(1)
    assert len(history) == 1
    assert history[0].activity_type == "distance"
    assert history[0].distance_km == 2.4


@pytest.mark.anyio
async def test_invalid_weight_delta_answers_callback_once_with_alert(tmp_path: Path) -> None:
    app, context = build_runtime(tmp_path)
    state = app.get_chat_state(context, 1)
    state.mode = "trainer_editing_weights"
    state.payload = {
        "group_id": "legs",
        "exercise_id": "squat",
        "sets_count": 1,
        "active_set": 0,
        "base_weight": 1000.0,
        "weights": [1000.0],
    }
    query = SimpleNamespace(
        data="trainer:delta:10",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=1, username="tester", full_name="Test User"),
    )

    await on_button(app, update, context)

    query.answer.assert_awaited_once_with("Вес должен быть от 0 до 1000 кг", show_alert=True)
    assert state.payload["weights"] == [1000.0]


@pytest.mark.anyio
async def test_increasing_set_weight_raises_lighter_following_sets(tmp_path: Path) -> None:
    app, context = build_runtime(tmp_path)
    state = app.get_chat_state(context, 1)
    state.mode = "trainer_editing_weights"
    state.payload = {
        "group_id": "legs",
        "exercise_id": "squat",
        "sets_count": 3,
        "active_set": 0,
        "base_weight": 10.0,
        "weights": [10.0, 10.0, 17.5],
    }

    await press(app, context, "trainer:delta:5")

    assert state.payload["weights"] == [15.0, 15.0, 17.5]

    state.payload["active_set"] = 1
    await press(app, context, "trainer:delta:5")

    assert state.payload["weights"] == [15.0, 20.0, 20.0]


@pytest.mark.anyio
async def test_manual_weight_raises_lighter_following_sets(tmp_path: Path) -> None:
    app, context = build_runtime(tmp_path)
    state = app.get_chat_state(context, 1)
    state.mode = "trainer_manual_weight"
    state.payload = {
        "group_id": "legs",
        "exercise_id": "squat",
        "sets_count": 3,
        "active_set": 0,
        "base_weight": 10.0,
        "weights": [10.0, 10.0, 12.5],
    }
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=1, username="tester", full_name="Test User"),
        message=SimpleNamespace(text="15"),
    )

    await on_text(app, update, context)

    assert state.payload["weights"] == [15.0, 15.0, 15.0]


@pytest.mark.anyio
async def test_new_workout_reuses_last_weights_and_extends_last_known_weight(tmp_path: Path) -> None:
    app, context = build_runtime(tmp_path)
    app.trainer_database.save_workout(
        telegram_user_id=1,
        username="tester",
        full_name="Test User",
        group_id="legs",
        group_name="Ноги",
        exercise_id="squat",
        exercise_name="Приседания со штангой",
        reps=(12,),
        weights=(15,),
        base_weight=10,
    )

    await press(app, context, "trainer:workout")
    await press(app, context, "trainer:group:legs")
    await press(app, context, "trainer:exercise:squat")
    await press(app, context, "trainer:sets:3")

    state = app.get_chat_state(context, 1)
    assert state.mode == "trainer_editing_weights"
    assert state.payload["weights"] == [15.0, 15.0, 15.0]


def test_application_uses_workout_database_next_to_notes_by_default(tmp_path: Path) -> None:
    app, _ = build_runtime(tmp_path)

    assert app.trainer_database.path == tmp_path / "workouts.sqlite3"
    assert app.trainer_catalog.get_exercise("bench_press") is not None
