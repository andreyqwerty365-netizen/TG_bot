from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence
from zoneinfo import ZoneInfo


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ExerciseProfile:
    base_weight: float
    last_weights: tuple[float, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WorkoutSummary:
    completed_at: str
    group_name: str
    exercise_id: str
    exercise_name: str
    activity_type: str
    sets_count: int
    weights: tuple[float, ...]
    reps: tuple[int, ...]
    distance_km: float | None


@dataclass(frozen=True, slots=True)
class HistoryCleanupResult:
    applied: bool
    removed_workout_ids: tuple[int, ...]
    backup_path: Path


HISTORY_CLEANUP_NAME = "remove-selected-test-workouts-2026-08-26-v1"
HISTORY_CLEANUP_BACKUP_NAME = "workouts-before-test-cleanup-20260826.sqlite3"
CURRENT_EXERCISE_NAMES = {
    "lat_pulldown": "Верхний хват",
    "seated_cable_row": "Нижний хват",
    "ez_bar_curl": "Поднятие грифа",
    "alternating_dumbbell_curl": "Hammer",
    "triceps_pushdown": "Трицепс",
    "pec_deck": "Бабочка",
    "treadmill_walking": "Ходьба на дорожке",
}
SELECTED_TEST_WORKOUTS = Counter(
    {
        ("24.08.2026", "Верхний хват", (30.0, 35.0, 40.0)): 4,
        ("24.08.2026", "Нижний хват", (25.0, 30.0, 30.0)): 2,
        ("24.08.2026", "Hammer", (10.0, 12.0, 14.0)): 1,
        ("24.08.2026", "Бабочка", (40.0, 45.0, 50.0)): 1,
        ("26.08.2026", "Верхний хват", (30.0, 35.0, 35.0)): 1,
    }
)


class TrainerDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        self.cleanup_selected_test_history(ZoneInfo("Europe/Moscow"))

    def init(self) -> None:
        """Create or upgrade the workout schema. Safe to call repeatedly."""
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        PRAGMA journal_mode = WAL;

        CREATE TABLE IF NOT EXISTS users (
            telegram_user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS exercise_profiles (
            telegram_user_id INTEGER NOT NULL,
            exercise_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            group_name TEXT NOT NULL,
            exercise_name TEXT NOT NULL,
            base_weight REAL NOT NULL CHECK (base_weight >= 0),
            last_weights_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, exercise_id),
            FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
        );

        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            group_id TEXT NOT NULL,
            group_name TEXT NOT NULL,
            exercise_id TEXT NOT NULL,
            exercise_name TEXT NOT NULL,
            activity_type TEXT NOT NULL DEFAULT 'strength'
                CHECK (activity_type IN ('strength', 'distance')),
            sets_count INTEGER NOT NULL CHECK (sets_count BETWEEN 0 AND 3),
            distance_km REAL CHECK (distance_km IS NULL OR distance_km > 0),
            completed_at TEXT NOT NULL,
            FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
        );

        CREATE TABLE IF NOT EXISTS workout_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_id INTEGER NOT NULL,
            set_number INTEGER NOT NULL CHECK (set_number BETWEEN 1 AND 3),
            reps INTEGER NOT NULL CHECK (reps > 0),
            weight REAL NOT NULL CHECK (weight >= 0),
            FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE,
            UNIQUE (workout_id, set_number)
        );

        CREATE TABLE IF NOT EXISTS active_base_sessions (
            telegram_user_id INTEGER PRIMARY KEY,
            completed_ids_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS data_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_workouts_user_date
            ON workouts(telegram_user_id, completed_at DESC);
        """
        with self._lock, self._connection() as connection:
            connection.executescript(schema)
            connection.commit()

    def cleanup_selected_test_history(
        self, local_timezone: ZoneInfo
    ) -> HistoryCleanupResult:
        backup_path = self.path.with_name(HISTORY_CLEANUP_BACKUP_NAME)
        with self._lock, self._connection() as connection:
            applied = connection.execute(
                "SELECT 1 FROM data_migrations WHERE name = ?",
                (HISTORY_CLEANUP_NAME,),
            ).fetchone()
            if applied is not None:
                return HistoryCleanupResult(False, (), backup_path)

            workout_rows = connection.execute(
                """
                SELECT id, telegram_user_id, completed_at, exercise_name
                FROM workouts
                WHERE activity_type = 'strength'
                ORDER BY id
                """
            ).fetchall()
            candidate_ids: list[int] = []
            candidate_users: set[int] = set()
            found = Counter()
            for workout in workout_rows:
                weights = tuple(
                    float(row["weight"])
                    for row in connection.execute(
                        """
                        SELECT weight FROM workout_sets
                        WHERE workout_id = ? ORDER BY set_number
                        """,
                        (workout["id"],),
                    ).fetchall()
                )
                local_date = (
                    datetime.fromisoformat(workout["completed_at"])
                    .astimezone(local_timezone)
                    .strftime("%d.%m.%Y")
                )
                key = (local_date, workout["exercise_name"], weights)
                if key in SELECTED_TEST_WORKOUTS:
                    found[key] += 1
                    candidate_ids.append(int(workout["id"]))
                    candidate_users.add(int(workout["telegram_user_id"]))

            if found != SELECTED_TEST_WORKOUTS:
                return HistoryCleanupResult(False, (), backup_path)

            if not backup_path.exists():
                with sqlite3.connect(backup_path) as backup:
                    connection.backup(backup)

            try:
                connection.execute("BEGIN IMMEDIATE")
                placeholders = ",".join("?" for _ in candidate_ids)
                connection.execute(
                    f"DELETE FROM workouts WHERE id IN ({placeholders})",
                    candidate_ids,
                )

                for exercise_id, exercise_name in CURRENT_EXERCISE_NAMES.items():
                    connection.execute(
                        "UPDATE workouts SET exercise_name = ? WHERE exercise_id = ?",
                        (exercise_name, exercise_id),
                    )
                    connection.execute(
                        "UPDATE exercise_profiles SET exercise_name = ? WHERE exercise_id = ?",
                        (exercise_name, exercise_id),
                    )

                for telegram_user_id in candidate_users:
                    connection.execute(
                        "DELETE FROM active_base_sessions WHERE telegram_user_id = ?",
                        (telegram_user_id,),
                    )
                    profiles = connection.execute(
                        """
                        SELECT exercise_id FROM exercise_profiles
                        WHERE telegram_user_id = ?
                        """,
                        (telegram_user_id,),
                    ).fetchall()
                    for profile in profiles:
                        latest = connection.execute(
                            """
                            SELECT id, group_id, group_name, exercise_name, completed_at
                            FROM workouts
                            WHERE telegram_user_id = ? AND exercise_id = ?
                                  AND activity_type = 'strength'
                            ORDER BY completed_at DESC, id DESC
                            LIMIT 1
                            """,
                            (telegram_user_id, profile["exercise_id"]),
                        ).fetchone()
                        if latest is None:
                            connection.execute(
                                """
                                DELETE FROM exercise_profiles
                                WHERE telegram_user_id = ? AND exercise_id = ?
                                """,
                                (telegram_user_id, profile["exercise_id"]),
                            )
                            continue
                        latest_weights = [
                            float(row["weight"])
                            for row in connection.execute(
                                """
                                SELECT weight FROM workout_sets
                                WHERE workout_id = ? ORDER BY set_number
                                """,
                                (latest["id"],),
                            ).fetchall()
                        ]
                        connection.execute(
                            """
                            UPDATE exercise_profiles
                            SET group_id = ?, group_name = ?, exercise_name = ?,
                                last_weights_json = ?, updated_at = ?
                            WHERE telegram_user_id = ? AND exercise_id = ?
                            """,
                            (
                                latest["group_id"],
                                latest["group_name"],
                                CURRENT_EXERCISE_NAMES.get(
                                    profile["exercise_id"], latest["exercise_name"]
                                ),
                                json.dumps(latest_weights, ensure_ascii=False),
                                latest["completed_at"],
                                telegram_user_id,
                                profile["exercise_id"],
                            ),
                        )

                connection.execute(
                    "INSERT INTO data_migrations (name, applied_at) VALUES (?, ?)",
                    (HISTORY_CLEANUP_NAME, utc_now_iso()),
                )
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"SQLite quick_check failed: {integrity}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return HistoryCleanupResult(True, tuple(candidate_ids), backup_path)

    def get_active_base_session(
        self, telegram_user_id: int
    ) -> tuple[str, ...] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT completed_ids_json
                FROM active_base_sessions
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        values = json.loads(row["completed_ids_json"])
        return tuple(str(value) for value in values)

    def save_active_base_session(
        self, telegram_user_id: int, completed_ids: Sequence[str]
    ) -> None:
        now = utc_now_iso()
        unique_ids = tuple(dict.fromkeys(str(value) for value in completed_ids))
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO active_base_sessions (
                    telegram_user_id, completed_ids_json, started_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    completed_ids_json = excluded.completed_ids_json,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    json.dumps(unique_ids, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.commit()

    def clear_active_base_session(self, telegram_user_id: int) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM active_base_sessions WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            connection.commit()

    @staticmethod
    def _upsert_user(
        connection: sqlite3.Connection,
        telegram_user_id: int,
        username: str | None,
        full_name: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO users (telegram_user_id, username, full_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                updated_at = excluded.updated_at
            """,
            (telegram_user_id, username, full_name, now, now),
        )

    def get_profile(self, telegram_user_id: int, exercise_id: str) -> ExerciseProfile | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT base_weight, last_weights_json, created_at, updated_at
                FROM exercise_profiles
                WHERE telegram_user_id = ? AND exercise_id = ?
                """,
                (telegram_user_id, exercise_id),
            ).fetchone()
        if row is None:
            return None
        return ExerciseProfile(
            base_weight=float(row["base_weight"]),
            last_weights=tuple(float(value) for value in json.loads(row["last_weights_json"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_workout(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
        full_name: str,
        group_id: str,
        group_name: str,
        exercise_id: str,
        exercise_name: str,
        reps: Sequence[int],
        weights: Sequence[float],
        base_weight: float,
    ) -> int:
        if not 1 <= len(weights) <= 3 or len(reps) != len(weights):
            raise ValueError("Нужно передать от 1 до 3 подходов и одинаковое число повторений")
        if base_weight < 0 or any(weight < 0 for weight in weights):
            raise ValueError("Вес не может быть отрицательным")

        now = utc_now_iso()
        clean_weights = [round(float(weight), 2) for weight in weights]
        clean_base_weight = round(float(base_weight), 2)

        with self._lock, self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._upsert_user(connection, telegram_user_id, username, full_name, now)
                cursor = connection.execute(
                    """
                    INSERT INTO workouts (
                        telegram_user_id, group_id, group_name, exercise_id,
                        exercise_name, activity_type, sets_count, distance_km, completed_at
                    ) VALUES (?, ?, ?, ?, ?, 'strength', ?, NULL, ?)
                    """,
                    (
                        telegram_user_id,
                        group_id,
                        group_name,
                        exercise_id,
                        exercise_name,
                        len(clean_weights),
                        now,
                    ),
                )
                workout_id = int(cursor.lastrowid)
                connection.executemany(
                    """
                    INSERT INTO workout_sets (workout_id, set_number, reps, weight)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (workout_id, index, int(rep), weight)
                        for index, (rep, weight) in enumerate(
                            zip(reps, clean_weights, strict=True), start=1
                        )
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO exercise_profiles (
                        telegram_user_id, exercise_id, group_id, group_name,
                        exercise_name, base_weight, last_weights_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_user_id, exercise_id) DO UPDATE SET
                        group_id = excluded.group_id,
                        group_name = excluded.group_name,
                        exercise_name = excluded.exercise_name,
                        last_weights_json = excluded.last_weights_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        telegram_user_id,
                        exercise_id,
                        group_id,
                        group_name,
                        exercise_name,
                        clean_base_weight,
                        json.dumps(clean_weights, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return workout_id

    def save_distance_activity(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
        full_name: str,
        group_id: str,
        group_name: str,
        exercise_id: str,
        exercise_name: str,
        distance_km: float,
    ) -> int:
        clean_distance = round(float(distance_km), 3)
        if not 0 < clean_distance <= 1000:
            raise ValueError("Дистанция должна быть больше 0 и не больше 1000 км")

        now = utc_now_iso()
        with self._lock, self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._upsert_user(connection, telegram_user_id, username, full_name, now)
                cursor = connection.execute(
                    """
                    INSERT INTO workouts (
                        telegram_user_id, group_id, group_name, exercise_id,
                        exercise_name, activity_type, sets_count, distance_km, completed_at
                    ) VALUES (?, ?, ?, ?, ?, 'distance', 0, ?, ?)
                    """,
                    (
                        telegram_user_id,
                        group_id,
                        group_name,
                        exercise_id,
                        exercise_name,
                        clean_distance,
                        now,
                    ),
                )
                workout_id = int(cursor.lastrowid)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return workout_id

    def get_recent_workouts(
        self, telegram_user_id: int, limit: int = 10
    ) -> list[WorkoutSummary]:
        safe_limit = max(1, min(int(limit), 50))
        with self._lock, self._connection() as connection:
            workout_rows = connection.execute(
                """
                SELECT id, completed_at, group_name, exercise_id, exercise_name, activity_type,
                       sets_count, distance_km
                FROM workouts
                WHERE telegram_user_id = ?
                ORDER BY completed_at DESC, id DESC
                LIMIT ?
                """,
                (telegram_user_id, safe_limit),
            ).fetchall()

            result: list[WorkoutSummary] = []
            for workout in workout_rows:
                set_rows = connection.execute(
                    """
                    SELECT reps, weight
                    FROM workout_sets
                    WHERE workout_id = ?
                    ORDER BY set_number
                    """,
                    (workout["id"],),
                ).fetchall()
                result.append(
                    WorkoutSummary(
                        completed_at=workout["completed_at"],
                        group_name=workout["group_name"],
                        exercise_id=workout["exercise_id"],
                        exercise_name=workout["exercise_name"],
                        activity_type=workout["activity_type"],
                        sets_count=int(workout["sets_count"]),
                        weights=tuple(float(row["weight"]) for row in set_rows),
                        reps=tuple(int(row["reps"]) for row in set_rows),
                        distance_km=(
                            float(workout["distance_km"])
                            if workout["distance_km"] is not None
                            else None
                        ),
                    )
                )
        return result

    def get_export_sets(self, telegram_user_id: int) -> list[sqlite3.Row]:
        with self._lock, self._connection() as connection:
            return connection.execute(
                """
                SELECT
                    w.id AS workout_id,
                    w.completed_at,
                    w.group_name,
                    w.exercise_id,
                    w.exercise_name,
                    w.sets_count,
                    s.set_number,
                    s.reps,
                    s.weight,
                    p.base_weight
                FROM workouts AS w
                JOIN workout_sets AS s ON s.workout_id = w.id
                LEFT JOIN exercise_profiles AS p
                    ON p.telegram_user_id = w.telegram_user_id
                    AND p.exercise_id = w.exercise_id
                WHERE w.telegram_user_id = ?
                ORDER BY w.completed_at, w.id, s.set_number
                """,
                (telegram_user_id,),
            ).fetchall()

    def get_export_profiles(self, telegram_user_id: int) -> list[sqlite3.Row]:
        with self._lock, self._connection() as connection:
            return connection.execute(
                """
                SELECT group_name, exercise_name, base_weight, last_weights_json,
                       created_at, updated_at
                FROM exercise_profiles
                WHERE telegram_user_id = ?
                ORDER BY group_name, exercise_name
                """,
                (telegram_user_id,),
            ).fetchall()

    def get_export_distances(self, telegram_user_id: int) -> list[sqlite3.Row]:
        with self._lock, self._connection() as connection:
            return connection.execute(
                """
                SELECT id AS workout_id, completed_at, group_name, exercise_name, distance_km
                FROM workouts
                WHERE telegram_user_id = ? AND activity_type = 'distance'
                ORDER BY completed_at, id
                """,
                (telegram_user_id,),
            ).fetchall()
