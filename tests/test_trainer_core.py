from __future__ import annotations

import importlib
import importlib.util
import json
import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_trainer_module(name: str):
    full_name = f"bot.trainer.{name}"
    assert importlib.util.find_spec(full_name) is not None, f"Missing trainer module: {full_name}"
    return importlib.import_module(full_name)


def test_catalog_supports_strength_and_distance_exercises() -> None:
    catalog_module = load_trainer_module("catalog")
    catalog = catalog_module.ExerciseCatalog(PROJECT_DIR / "exercises.json")

    treadmill = catalog.get_exercise("treadmill_walking")
    bench = catalog.get_exercise("bench_press")

    assert treadmill is not None
    assert treadmill[1].type == "distance"
    assert treadmill[1].weight_steps == ()
    assert bench is not None
    assert bench[1].type == "strength"
    assert 5.0 in bench[1].weight_steps
    assert bench[1].image_path is not None
    assert bench[1].image_path.is_file()


def test_catalog_uses_short_exercise_names_and_includes_calves() -> None:
    catalog_module = load_trainer_module("catalog")
    catalog = catalog_module.ExerciseCatalog(PROJECT_DIR / "exercises.json")

    expected_names = {
        "lat_pulldown": "Верхний хват",
        "seated_cable_row": "Нижний хват",
        "calf_raise": "Икры",
        "ez_bar_curl": "Поднятие грифа",
        "alternating_dumbbell_curl": "Hammer",
        "triceps_pushdown": "Трицепс",
        "pec_deck": "Бабочка",
    }

    for exercise_id, expected_name in expected_names.items():
        resolved = catalog.get_exercise(exercise_id)
        assert resolved is not None
        assert resolved[1].name == expected_name

    calves = catalog.get_exercise("calf_raise")
    assert calves is not None
    assert calves[0].id == "legs"


def test_every_exercise_has_four_frame_card_and_technique_notes() -> None:
    catalog_module = load_trainer_module("catalog")
    catalog = catalog_module.ExerciseCatalog(PROJECT_DIR / "exercises.json")

    for group in catalog.groups:
        for exercise in group.exercises:
            assert exercise.image_path is not None, exercise.name
            assert exercise.image_path.is_file(), exercise.name
            assert len(exercise.technique) >= 3, exercise.name
            assert len(exercise.mistakes) >= 2, exercise.name


def test_catalog_rejects_duplicate_exercise_ids(tmp_path: Path) -> None:
    catalog_module = load_trainer_module("catalog")
    path = tmp_path / "exercises.json"
    path.write_text(
        json.dumps(
            {
                "groups": [
                    {"id": "one", "name": "Первая", "exercises": [{"id": "same", "name": "A", "weight_steps": [5]}]},
                    {"id": "two", "name": "Вторая", "exercises": [{"id": "same", "name": "B", "weight_steps": [5]}]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Повторяющийся ID упражнения"):
        catalog_module.ExerciseCatalog(path)


def test_baseline_is_fixed_and_recent_weights_are_updated(tmp_path: Path) -> None:
    database_module = load_trainer_module("database")
    database = database_module.TrainerDatabase(tmp_path / "workouts.sqlite3")
    database.init()

    database.save_workout(
        telegram_user_id=123,
        username="tester",
        full_name="Test User",
        group_id="chest",
        group_name="Грудь",
        exercise_id="bench_press",
        exercise_name="Жим лёжа",
        reps=(12, 10, 8),
        weights=(40, 45, 50),
        base_weight=40,
    )
    database.save_workout(
        telegram_user_id=123,
        username="tester",
        full_name="Test User",
        group_id="chest",
        group_name="Грудь",
        exercise_id="bench_press",
        exercise_name="Жим лёжа",
        reps=(12, 10, 8),
        weights=(45, 50, 55),
        base_weight=999,
    )

    profile = database.get_profile(123, "bench_press")
    assert profile is not None
    assert profile.base_weight == 40
    assert profile.last_weights == (45, 50, 55)


def test_active_base_session_persists_across_database_instances(tmp_path: Path) -> None:
    database_module = load_trainer_module("database")
    path = tmp_path / "workouts.sqlite3"
    first = database_module.TrainerDatabase(path)

    first.save_active_base_session(123, ("lat_pulldown", "pec_deck"))

    restarted = database_module.TrainerDatabase(path)
    assert restarted.get_active_base_session(123) == (
        "lat_pulldown",
        "pec_deck",
    )

    restarted.clear_active_base_session(123)
    assert first.get_active_base_session(123) is None


def test_strength_cardio_history_and_excel_export(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    database_module = load_trainer_module("database")
    exporter_module = load_trainer_module("exporter")
    database = database_module.TrainerDatabase(tmp_path / "workouts.sqlite3")
    database.init()

    strength_id = database.save_workout(
        telegram_user_id=123,
        username="tester",
        full_name="Test User",
        group_id="chest",
        group_name="Грудь",
        exercise_id="bench_press",
        exercise_name="Жим лёжа",
        reps=(12, 10, 8),
        weights=(40, 45, 50),
        base_weight=40,
    )
    cardio_id = database.save_distance_activity(
        telegram_user_id=123,
        username="tester",
        full_name="Test User",
        group_id="cardio",
        group_name="Кардио",
        exercise_id="treadmill_walking",
        exercise_name="Ходьба на дорожке",
        distance_km=2.4,
    )

    assert cardio_id > strength_id > 0
    history = database.get_recent_workouts(123)
    assert [item.activity_type for item in history] == ["distance", "strength"]
    assert history[0].distance_km == 2.4

    content = exporter_module.build_workout_export(database, 123, ZoneInfo("Europe/Moscow"))
    workbook = openpyxl.load_workbook(BytesIO(content), data_only=True)
    assert workbook.sheetnames == ["История"]

    sheet = workbook["История"]
    assert list(sheet.values) == [
        ("Дата", "Упражнение", "1-й подход", "2-й подход", "3-й подход"),
        (
            datetime.fromisoformat(history[1].completed_at)
            .astimezone(ZoneInfo("Europe/Moscow"))
            .strftime("%d.%m.%Y"),
            "Жим лёжа",
            40,
            45,
            50,
        ),
        (
            datetime.fromisoformat(history[0].completed_at)
            .astimezone(ZoneInfo("Europe/Moscow"))
            .strftime("%d.%m.%Y"),
            "Ходьба на дорожке",
            "2,4 км",
            None,
            None,
        ),
    ]
    assert sheet["A2"].number_format == "@"
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref is None
    assert len(sheet.tables) == 0
    assert sheet["A2"].fill.fgColor.rgb == "FFFFFFFF"
    assert sheet["A2"].font.color.rgb == "FF111827"


def test_selected_test_history_cleanup_is_exact_and_recoverable(tmp_path: Path) -> None:
    database_module = load_trainer_module("database")
    path = tmp_path / "workouts.sqlite3"
    database = database_module.TrainerDatabase(path)

    def save_strength(
        exercise_id: str,
        exercise_name: str,
        weights: tuple[float, ...],
        completed_at: str,
    ) -> int:
        workout_id = database.save_workout(
            telegram_user_id=123,
            username="tester",
            full_name="Test User",
            group_id="test",
            group_name="Тест",
            exercise_id=exercise_id,
            exercise_name=exercise_name,
            reps=(12, 10, 8)[: len(weights)],
            weights=weights,
            base_weight=weights[0],
        )
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE workouts SET completed_at = ? WHERE id = ?",
                (completed_at, workout_id),
            )
            connection.commit()
        return workout_id

    kept_real_id = save_strength(
        "lat_pulldown",
        "Тяга верхнего блока широким хватом",
        (30, 35, 40),
        "2026-08-24T12:12:00+00:00",
    )
    selected_ids = [
        save_strength("lat_pulldown", "Верхний хват", (30, 35, 40), "2026-08-24T14:56:00+00:00"),
        save_strength("lat_pulldown", "Верхний хват", (30, 35, 40), "2026-08-24T14:57:00+00:00"),
        save_strength("lat_pulldown", "Верхний хват", (30, 35, 40), "2026-08-24T15:08:00+00:00"),
        save_strength("seated_cable_row", "Нижний хват", (25, 30, 30), "2026-08-24T15:29:00+00:00"),
        save_strength("lat_pulldown", "Верхний хват", (30, 35, 40), "2026-08-24T15:37:00+00:00"),
        save_strength("seated_cable_row", "Нижний хват", (25, 30, 30), "2026-08-24T15:37:30+00:00"),
        save_strength("alternating_dumbbell_curl", "Hammer", (10, 12, 14), "2026-08-24T15:38:00+00:00"),
        save_strength("pec_deck", "Бабочка", (40, 45, 50), "2026-08-24T15:38:30+00:00"),
        save_strength("lat_pulldown", "Верхний хват", (30, 35, 35), "2026-08-26T08:04:00+00:00"),
    ]
    kept_25_id = save_strength(
        "lat_pulldown",
        "Верхний хват",
        (30, 35),
        "2026-08-25T08:19:00+00:00",
    )
    database.save_active_base_session(123, ("lat_pulldown",))

    result = database.cleanup_selected_test_history(ZoneInfo("Europe/Moscow"))

    assert result.applied is True
    assert result.removed_workout_ids == tuple(selected_ids)
    assert result.backup_path.is_file()
    assert database.get_active_base_session(123) is None

    with sqlite3.connect(path) as connection:
        remaining = connection.execute(
            "SELECT id, exercise_name FROM workouts ORDER BY id"
        ).fetchall()
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
    assert remaining == [
        (kept_real_id, "Верхний хват"),
        (kept_25_id, "Верхний хват"),
    ]
    assert integrity == "ok"
    assert database.get_profile(123, "lat_pulldown").last_weights == (30, 35)

    repeated = database.cleanup_selected_test_history(ZoneInfo("Europe/Moscow"))
    assert repeated.applied is False
    assert repeated.removed_workout_ids == ()


def test_historical_workout_for_23_august_is_added_once(tmp_path: Path) -> None:
    database_module = load_trainer_module("database")
    path = tmp_path / "workouts.sqlite3"
    database = database_module.TrainerDatabase(path)
    database.save_workout(
        telegram_user_id=123,
        username="tester",
        full_name="Test User",
        group_id="back",
        group_name="Спина",
        exercise_id="lat_pulldown",
        exercise_name="Верхний хват",
        reps=(12, 10, 8),
        weights=(35, 40, 45),
        base_weight=35,
    )
    profile_before = database.get_profile(123, "lat_pulldown")

    result = database.add_historical_workout_20260823(
        ZoneInfo("Europe/Moscow")
    )

    assert result.applied is True
    assert len(result.inserted_workout_ids) == 5
    assert result.backup_path.is_file()
    assert database.get_profile(123, "lat_pulldown") == profile_before

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, exercise_name, activity_type, distance_km, completed_at
            FROM workouts
            WHERE id IN (?, ?, ?, ?, ?)
            ORDER BY completed_at
            """,
            result.inserted_workout_ids,
        ).fetchall()
        sets = {
            row["exercise_name"]: tuple(
                item[0]
                for item in connection.execute(
                    "SELECT weight FROM workout_sets WHERE workout_id = ? ORDER BY set_number",
                    (row["id"],),
                ).fetchall()
            )
            for row in rows
            if row["activity_type"] == "strength"
        }

    assert [row["exercise_name"] for row in rows] == [
        "Верхний хват",
        "Нижний хват",
        "Поднятие грифа",
        "Трицепс",
        "Ходьба на дорожке",
    ]
    assert all(row["completed_at"].startswith("2026-08-23T") for row in rows)
    assert sets == {
        "Верхний хват": (30, 35, 40),
        "Нижний хват": (25, 30, 35),
        "Поднятие грифа": (5, 15, 17.5),
        "Трицепс": (30, 35, 40),
    }
    assert rows[-1]["distance_km"] == 1.7

    repeated = database.add_historical_workout_20260823(
        ZoneInfo("Europe/Moscow")
    )
    assert repeated.applied is False
    assert repeated.inserted_workout_ids == ()
