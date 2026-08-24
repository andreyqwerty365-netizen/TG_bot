from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence


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


class TrainerDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

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

        CREATE INDEX IF NOT EXISTS idx_workouts_user_date
            ON workouts(telegram_user_id, completed_at DESC);
        """
        with self._lock, self._connection() as connection:
            connection.executescript(schema)
            connection.commit()

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
