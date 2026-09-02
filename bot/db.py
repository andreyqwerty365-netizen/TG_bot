from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from .models import ChatSettingsRecord, Note, Reminder, RoutineSettings, RoutineTask, ShiftDay
from .utils.date_utils import iso_utc, parse_iso_utc, utc_now


class Database:
    def __init__(self, db_path: Path, default_tz_offset_minutes: int = 0) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_tz_offset_minutes = default_tz_offset_minutes
        self._fts_ready: bool | None = None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    repeat_rule TEXT,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    done_at TEXT,
                    created_at TEXT NOT NULL,
                    job_name TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_settings (
                    chat_id INTEGER PRIMARY KEY,
                    tz_offset_minutes INTEGER NOT NULL DEFAULT 0,
                    dayplan_enabled INTEGER NOT NULL DEFAULT 0,
                    dayplan_time TEXT,
                    active_message_id INTEGER
                );

                CREATE TABLE IF NOT EXISTS routine_settings (
                    chat_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    digest_interval_hours INTEGER NOT NULL DEFAULT 3
                );
                CREATE TABLE IF NOT EXISTS shift_templates (
                    chat_id INTEGER NOT NULL,
                    shift_type TEXT NOT NULL CHECK(shift_type IN ('day', 'night', 'off')),
                    wake_time TEXT NOT NULL,
                    PRIMARY KEY(chat_id, shift_type)
                );
                CREATE TABLE IF NOT EXISTS shift_schedule (
                    chat_id INTEGER NOT NULL,
                    routine_date TEXT NOT NULL,
                    shift_type TEXT NOT NULL CHECK(shift_type IN ('day', 'night', 'off')),
                    PRIMARY KEY(chat_id, routine_date)
                );
                CREATE TABLE IF NOT EXISTS routine_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    shift_type TEXT NOT NULL CHECK(shift_type IN ('all', 'day', 'night', 'off')),
                    offset_minutes INTEGER NOT NULL,
                    repeat_in_digest INTEGER NOT NULL DEFAULT 0,
                    expires_after_minutes INTEGER NOT NULL DEFAULT 960,
                    is_active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS routine_task_status (
                    chat_id INTEGER NOT NULL,
                    task_id INTEGER NOT NULL,
                    routine_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('done', 'skipped')),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(chat_id, task_id, routine_date),
                    FOREIGN KEY(task_id) REFERENCES routine_tasks(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS routine_deliveries (
                    chat_id INTEGER NOT NULL,
                    delivery_key TEXT NOT NULL,
                    delivered_at TEXT NOT NULL,
                    PRIMARY KEY(chat_id, delivery_key)
                );
                """
            )
            self._migrate_legacy_columns(conn)
            conn.executescript(
                """

                CREATE INDEX IF NOT EXISTS idx_notes_chat_archived_id
                    ON notes(chat_id, is_archived, id DESC);
                CREATE INDEX IF NOT EXISTS idx_reminders_chat_archived_time
                    ON reminders(chat_id, is_archived, remind_at ASC);
                CREATE INDEX IF NOT EXISTS idx_reminders_active_lookup
                    ON reminders(is_archived, done_at, remind_at ASC);
                CREATE INDEX IF NOT EXISTS idx_routine_tasks_chat_active
                    ON routine_tasks(chat_id, is_active, shift_type);
                CREATE INDEX IF NOT EXISTS idx_shift_schedule_chat_date
                    ON shift_schedule(chat_id, routine_date);
                CREATE INDEX IF NOT EXISTS idx_notes_chat_text
                    ON notes(chat_id, text);
                CREATE INDEX IF NOT EXISTS idx_reminders_chat_text
                    ON reminders(chat_id, text);
                """
            )
            self._try_init_fts(conn)

    def _migrate_legacy_columns(self, conn: sqlite3.Connection) -> None:
        for table, coldef in [
            ("notes", "is_archived INTEGER NOT NULL DEFAULT 0"),
            ("reminders", "job_name TEXT"),
            ("reminders", "repeat_rule TEXT"),
            ("reminders", "is_archived INTEGER NOT NULL DEFAULT 0"),
            ("reminders", "done_at TEXT"),
            ("reminders", "created_at TEXT"),
            ("chat_settings", "dayplan_enabled INTEGER NOT NULL DEFAULT 0"),
            ("chat_settings", "dayplan_time TEXT"),
            ("chat_settings", "active_message_id INTEGER"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

        now_iso = iso_utc(utc_now())
        conn.execute("UPDATE reminders SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL", (now_iso,))

    def _try_init_fts(self, conn: sqlite3.Connection) -> None:
        if self._fts_ready is False:
            return
        try:
            conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text, content='notes', content_rowid='id');
                CREATE VIRTUAL TABLE IF NOT EXISTS reminders_fts USING fts5(text, content='reminders', content_rowid='id');

                CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                    INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES('delete', old.id, old.text);
                END;
                CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES('delete', old.id, old.text);
                    INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
                END;

                CREATE TRIGGER IF NOT EXISTS reminders_ai AFTER INSERT ON reminders BEGIN
                    INSERT INTO reminders_fts(rowid, text) VALUES (new.id, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS reminders_ad AFTER DELETE ON reminders BEGIN
                    INSERT INTO reminders_fts(reminders_fts, rowid, text) VALUES('delete', old.id, old.text);
                END;
                CREATE TRIGGER IF NOT EXISTS reminders_au AFTER UPDATE ON reminders BEGIN
                    INSERT INTO reminders_fts(reminders_fts, rowid, text) VALUES('delete', old.id, old.text);
                    INSERT INTO reminders_fts(rowid, text) VALUES (new.id, new.text);
                END;
                """
            )
            conn.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
            conn.execute("INSERT INTO reminders_fts(reminders_fts) VALUES('rebuild')")
            self._fts_ready = True
        except sqlite3.OperationalError:
            self._fts_ready = False

    def get_chat_settings(self, chat_id: int) -> ChatSettingsRecord:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT chat_id, tz_offset_minutes, dayplan_enabled, dayplan_time FROM chat_settings WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return ChatSettingsRecord(
                chat_id=chat_id,
                tz_offset_minutes=self.default_tz_offset_minutes,
                dayplan_enabled=False,
                dayplan_time=None,
            )
        return ChatSettingsRecord(
            chat_id=row["chat_id"],
            tz_offset_minutes=int(row["tz_offset_minutes"]),
            dayplan_enabled=bool(row["dayplan_enabled"]),
            dayplan_time=row["dayplan_time"],
        )

    def set_timezone(self, chat_id: int, offset_minutes: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_settings(chat_id, tz_offset_minutes)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET tz_offset_minutes=excluded.tz_offset_minutes
                """,
                (chat_id, offset_minutes),
            )

    def set_dayplan(self, chat_id: int, enabled: bool, hhmm: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_settings(chat_id, tz_offset_minutes, dayplan_enabled, dayplan_time)
                VALUES (?, COALESCE((SELECT tz_offset_minutes FROM chat_settings WHERE chat_id=?), ?), ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    dayplan_enabled=excluded.dayplan_enabled,
                    dayplan_time=excluded.dayplan_time
                """,
                (chat_id, chat_id, self.default_tz_offset_minutes, 1 if enabled else 0, hhmm),
            )

    def get_active_message_id(self, chat_id: int) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT active_message_id FROM chat_settings WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
        if row is None or row["active_message_id"] is None:
            return None
        return int(row["active_message_id"])

    def set_active_message_id(self, chat_id: int, message_id: int | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_settings(chat_id, tz_offset_minutes, active_message_id)
                VALUES (?, COALESCE((SELECT tz_offset_minutes FROM chat_settings WHERE chat_id=?), ?), ?)
                ON CONFLICT(chat_id) DO UPDATE SET active_message_id=excluded.active_message_id
                """,
                (chat_id, chat_id, self.default_tz_offset_minutes, message_id),
            )

    def ensure_routine_profile(self, chat_id: int) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO routine_settings(chat_id) VALUES (?)", (chat_id,))
            for shift_type, wake_time in (("day", "07:00"), ("night", "19:00"), ("off", "09:00")):
                conn.execute("INSERT OR IGNORE INTO shift_templates VALUES (?, ?, ?)", (chat_id, shift_type, wake_time))

    def get_routine_settings(self, chat_id: int) -> RoutineSettings:
        self.ensure_routine_profile(chat_id)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM routine_settings WHERE chat_id=?", (chat_id,)).fetchone()
        return RoutineSettings(int(row["chat_id"]), bool(row["enabled"]), int(row["digest_interval_hours"]))

    def set_routine_enabled(self, chat_id: int, enabled: bool) -> None:
        self.ensure_routine_profile(chat_id)
        with self.connect() as conn:
            conn.execute("UPDATE routine_settings SET enabled=? WHERE chat_id=?", (int(enabled), chat_id))

    def set_routine_digest_interval(self, chat_id: int, hours: int) -> None:
        if hours not in {2, 3, 4}:
            raise ValueError("Digest interval must be 2, 3, or 4 hours")
        self.ensure_routine_profile(chat_id)
        with self.connect() as conn:
            conn.execute("UPDATE routine_settings SET digest_interval_hours=? WHERE chat_id=?", (hours, chat_id))

    def list_enabled_routine_chat_ids(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT chat_id FROM routine_settings WHERE enabled=1").fetchall()
        return [int(row["chat_id"]) for row in rows]

    def get_shift_wake_times(self, chat_id: int) -> dict[str, str]:
        self.ensure_routine_profile(chat_id)
        with self.connect() as conn:
            rows = conn.execute("SELECT shift_type, wake_time FROM shift_templates WHERE chat_id=?", (chat_id,)).fetchall()
        return {str(row["shift_type"]): str(row["wake_time"]) for row in rows}

    def set_shift_wake_time(self, chat_id: int, shift_type: str, wake_time: str) -> None:
        if shift_type not in {"day", "night", "off"}:
            raise ValueError("Unknown shift type")
        self.ensure_routine_profile(chat_id)
        with self.connect() as conn:
            conn.execute("UPDATE shift_templates SET wake_time=? WHERE chat_id=? AND shift_type=?", (wake_time, chat_id, shift_type))

    def set_shift_day(self, chat_id: int, routine_date, shift_type: str) -> None:
        if shift_type not in {"day", "night", "off"}:
            raise ValueError("Unknown shift type")
        self.ensure_routine_profile(chat_id)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO shift_schedule VALUES (?, ?, ?) ON CONFLICT(chat_id, routine_date) DO UPDATE SET shift_type=excluded.shift_type",
                (chat_id, routine_date.isoformat(), shift_type),
            )

    def get_shift_day(self, chat_id: int, routine_date) -> ShiftDay | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM shift_schedule WHERE chat_id=? AND routine_date=?", (chat_id, routine_date.isoformat())).fetchone()
        if row is None:
            return None
        from datetime import date
        return ShiftDay(int(row["chat_id"]), date.fromisoformat(row["routine_date"]), str(row["shift_type"]))

    def list_shift_days(self, chat_id: int, start_date, days: int) -> list[ShiftDay]:
        from datetime import date, timedelta
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shift_schedule WHERE chat_id=? AND routine_date>=? AND routine_date<? ORDER BY routine_date",
                (chat_id, start_date.isoformat(), (start_date + timedelta(days=days)).isoformat()),
            ).fetchall()
        return [ShiftDay(int(r["chat_id"]), date.fromisoformat(r["routine_date"]), str(r["shift_type"])) for r in rows]

    def add_routine_task(self, chat_id: int, text: str, shift_type: str, offset_minutes: int, repeat_in_digest: bool, expires_after_minutes: int) -> int:
        if shift_type not in {"all", "day", "night", "off"}:
            raise ValueError("Unknown shift type")
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO routine_tasks(chat_id,text,shift_type,offset_minutes,repeat_in_digest,expires_after_minutes) VALUES (?,?,?,?,?,?)",
                (chat_id, text.strip(), shift_type, offset_minutes, int(repeat_in_digest), expires_after_minutes),
            )
            return int(cur.lastrowid)

    def list_routine_tasks(self, chat_id: int, shift_type: str | None = None, active_only: bool = True) -> list[RoutineTask]:
        sql, params = "SELECT * FROM routine_tasks WHERE chat_id=?", [chat_id]
        if active_only:
            sql += " AND is_active=1"
        if shift_type is not None:
            sql += " AND shift_type IN ('all', ?)"
            params.append(shift_type)
        sql += " ORDER BY offset_minutes, id"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [RoutineTask(int(r["id"]), int(r["chat_id"]), str(r["text"]), str(r["shift_type"]), int(r["offset_minutes"]), bool(r["repeat_in_digest"]), int(r["expires_after_minutes"]), bool(r["is_active"])) for r in rows]

    def set_routine_task_active(self, chat_id: int, task_id: int, active: bool) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE routine_tasks SET is_active=? WHERE chat_id=? AND id=?", (int(active), chat_id, task_id))
            return cur.rowcount > 0

    def set_routine_task_status(self, chat_id: int, task_id: int, routine_date, status: str) -> None:
        if status not in {"done", "skipped"}:
            raise ValueError("Unknown routine task status")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO routine_task_status VALUES (?,?,?,?,?) ON CONFLICT(chat_id,task_id,routine_date) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at",
                (chat_id, task_id, routine_date.isoformat(), status, iso_utc(utc_now())),
            )

    def get_routine_task_statuses(self, chat_id: int, routine_date) -> dict[int, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT task_id,status FROM routine_task_status WHERE chat_id=? AND routine_date=?", (chat_id, routine_date.isoformat())).fetchall()
        return {int(row["task_id"]): str(row["status"]) for row in rows}

    def has_routine_delivery(self, chat_id: int, delivery_key: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM routine_deliveries WHERE chat_id=? AND delivery_key=?", (chat_id, delivery_key)).fetchone()
        return row is not None

    def record_routine_delivery(self, chat_id: int, delivery_key: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("INSERT OR IGNORE INTO routine_deliveries VALUES (?,?,?)", (chat_id, delivery_key, iso_utc(utc_now())))
            return cur.rowcount > 0

    def add_note(self, chat_id: int, text: str, created_at=None) -> int:
        created_at_value = iso_utc(created_at or utc_now())
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO notes(chat_id, text, created_at, is_archived) VALUES(?, ?, ?, 0)",
                (chat_id, text.strip(), created_at_value),
            )
            return int(cur.lastrowid)

    def list_notes(self, chat_id: int, archived: bool = False, limit: int = 50, offset: int = 0) -> list[Note]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, chat_id, text, created_at, is_archived FROM notes WHERE chat_id=? AND is_archived=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (chat_id, 1 if archived else 0, limit, offset),
            ).fetchall()
        rows = list(reversed(rows))
        return [
            Note(
                id=row["id"],
                chat_id=row["chat_id"],
                text=row["text"],
                created_at=parse_iso_utc(row["created_at"]),
                is_archived=bool(row["is_archived"]),
            )
            for row in rows
        ]

    def count_notes(self, chat_id: int, archived: bool = False) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM notes WHERE chat_id=? AND is_archived=?",
                (chat_id, 1 if archived else 0),
            ).fetchone()
        return int(row["count"])

    def search_notes(self, chat_id: int, query: str, archived: bool = False, limit: int = 20) -> list[Note]:
        normalized = self._normalized_query(query)
        with self.connect() as conn:
            if self._fts_ready:
                try:
                    rows = conn.execute(
                        """
                        SELECT n.id, n.chat_id, n.text, n.created_at, n.is_archived
                        FROM notes_fts f
                        JOIN notes n ON n.id = f.rowid
                        WHERE n.chat_id=? AND n.is_archived=? AND f.text MATCH ?
                        ORDER BY bm25(notes_fts), n.id DESC
                        LIMIT ?
                        """,
                        (chat_id, 1 if archived else 0, normalized, limit),
                    ).fetchall()
                    rows = list(reversed(rows))
                    return [
                        Note(
                            id=row["id"],
                            chat_id=row["chat_id"],
                            text=row["text"],
                            created_at=parse_iso_utc(row["created_at"]),
                            is_archived=bool(row["is_archived"]),
                        )
                        for row in rows
                    ]
                except sqlite3.OperationalError:
                    self._fts_ready = False
            rows = conn.execute(
                """
                SELECT id, chat_id, text, created_at, is_archived
                FROM notes
                WHERE chat_id=? AND is_archived=? AND lower(text) LIKE lower(?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, 1 if archived else 0, f"%{query.strip()}%", limit),
            ).fetchall()
        rows = list(reversed(rows))
        return [
            Note(
                id=row["id"],
                chat_id=row["chat_id"],
                text=row["text"],
                created_at=parse_iso_utc(row["created_at"]),
                is_archived=bool(row["is_archived"]),
            )
            for row in rows
        ]

    def get_note(self, chat_id: int, note_id: int) -> Note | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, chat_id, text, created_at, is_archived FROM notes WHERE chat_id=? AND id=?",
                (chat_id, note_id),
            ).fetchone()
        if row is None:
            return None
        return Note(row["id"], row["chat_id"], row["text"], parse_iso_utc(row["created_at"]), bool(row["is_archived"]))

    def update_note(self, chat_id: int, note_id: int, text: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE notes SET text=? WHERE chat_id=? AND id=?", (text.strip(), chat_id, note_id))
            return cur.rowcount > 0

    def archive_note(self, chat_id: int, note_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE notes SET is_archived=1 WHERE chat_id=? AND id=?", (chat_id, note_id))
            return cur.rowcount > 0

    def restore_note(self, chat_id: int, note_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE notes SET is_archived=0 WHERE chat_id=? AND id=?", (chat_id, note_id))
            return cur.rowcount > 0

    def delete_note(self, chat_id: int, note_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM notes WHERE chat_id=? AND id=?", (chat_id, note_id))
            return cur.rowcount > 0

    def add_reminder(self, chat_id: int, text: str, remind_at_utc, repeat_rule: str | None = None, *, created_at=None, done_at=None) -> int:
        created_at_value = iso_utc(created_at or utc_now())
        done_at_value = iso_utc(done_at) if done_at else None
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO reminders(chat_id, text, remind_at, repeat_rule, is_archived, done_at, created_at, job_name)
                VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
                """,
                (chat_id, text.strip(), iso_utc(remind_at_utc), repeat_rule, created_at_value, None),
            )
            reminder_id = int(cur.lastrowid)
            conn.execute("UPDATE reminders SET job_name=? WHERE id=?", (f"reminder:{reminder_id}", reminder_id))
            if done_at_value is not None:
                conn.execute("UPDATE reminders SET done_at=? WHERE id=?", (done_at_value, reminder_id))
            return reminder_id

    def get_reminder(self, chat_id: int, reminder_id: int) -> Reminder | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, chat_id, text, remind_at, repeat_rule, is_archived, done_at, created_at
                FROM reminders WHERE chat_id=? AND id=?
                """,
                (chat_id, reminder_id),
            ).fetchone()
        return self._row_to_reminder(row) if row else None

    def list_reminders(
        self,
        chat_id: int,
        archived: bool = False,
        include_done: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Reminder]:
        sql = """
            SELECT id, chat_id, text, remind_at, repeat_rule, is_archived, done_at, created_at
            FROM reminders
            WHERE chat_id=? AND is_archived=?
        """
        params: list[object] = [chat_id, 1 if archived else 0]
        if not include_done:
            sql += " AND done_at IS NULL"
        sql += " ORDER BY remind_at ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def count_reminders(self, chat_id: int, archived: bool = False, include_done: bool = True) -> int:
        sql = "SELECT COUNT(*) AS count FROM reminders WHERE chat_id=? AND is_archived=?"
        params: list[object] = [chat_id, 1 if archived else 0]
        if not include_done:
            sql += " AND done_at IS NULL"
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row["count"])

    def search_reminders(self, chat_id: int, query: str, archived: bool = False, include_done: bool = True, limit: int = 20) -> list[Reminder]:
        normalized = self._normalized_query(query)
        with self.connect() as conn:
            if self._fts_ready:
                try:
                    sql = """
                        SELECT r.id, r.chat_id, r.text, r.remind_at, r.repeat_rule, r.is_archived, r.done_at, r.created_at
                        FROM reminders_fts f
                        JOIN reminders r ON r.id = f.rowid
                        WHERE r.chat_id=? AND r.is_archived=? AND f.text MATCH ?
                    """
                    params: list[object] = [chat_id, 1 if archived else 0, normalized]
                    if not include_done:
                        sql += " AND r.done_at IS NULL"
                    sql += " ORDER BY bm25(reminders_fts), r.remind_at ASC LIMIT ?"
                    params.append(limit)
                    rows = conn.execute(sql, params).fetchall()
                    return [self._row_to_reminder(row) for row in rows]
                except sqlite3.OperationalError:
                    self._fts_ready = False
            sql = """
                SELECT id, chat_id, text, remind_at, repeat_rule, is_archived, done_at, created_at
                FROM reminders
                WHERE chat_id=? AND is_archived=? AND lower(text) LIKE lower(?)
            """
            params = [chat_id, 1 if archived else 0, f"%{query.strip()}%"]
            if not include_done:
                sql += " AND done_at IS NULL"
            sql += " ORDER BY remind_at ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def list_pending_reminders(self) -> list[Reminder]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, chat_id, text, remind_at, repeat_rule, is_archived, done_at, created_at
                FROM reminders
                WHERE is_archived=0 AND done_at IS NULL
                ORDER BY remind_at ASC
                """
            ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def update_reminder_text(self, chat_id: int, reminder_id: int, text: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE reminders SET text=? WHERE chat_id=? AND id=?", (text.strip(), chat_id, reminder_id))
            return cur.rowcount > 0

    def update_reminder_time(self, chat_id: int, reminder_id: int, remind_at_utc) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE reminders SET remind_at=? WHERE chat_id=? AND id=?",
                (iso_utc(remind_at_utc), chat_id, reminder_id),
            )
            return cur.rowcount > 0

    def update_reminder_repeat_rule(self, chat_id: int, reminder_id: int, repeat_rule: str | None) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE reminders SET repeat_rule=? WHERE chat_id=? AND id=?",
                (repeat_rule, chat_id, reminder_id),
            )
            return cur.rowcount > 0

    def mark_reminder_done(self, chat_id: int, reminder_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE reminders SET done_at=? WHERE chat_id=? AND id=?",
                (iso_utc(utc_now()), chat_id, reminder_id),
            )
            return cur.rowcount > 0

    def reopen_reminder(self, chat_id: int, reminder_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE reminders SET done_at=NULL WHERE chat_id=? AND id=?", (chat_id, reminder_id))
            return cur.rowcount > 0

    def archive_reminder(self, chat_id: int, reminder_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE reminders SET is_archived=1 WHERE chat_id=? AND id=?", (chat_id, reminder_id))
            return cur.rowcount > 0

    def archive_completed_reminders(self, chat_id: int) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE reminders SET is_archived=1 WHERE chat_id=? AND done_at IS NOT NULL AND is_archived=0",
                (chat_id,),
            )
            return cur.rowcount

    def restore_reminder(self, chat_id: int, reminder_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("UPDATE reminders SET is_archived=0 WHERE chat_id=? AND id=?", (chat_id, reminder_id))
            return cur.rowcount > 0

    def delete_reminder(self, chat_id: int, reminder_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM reminders WHERE chat_id=? AND id=?", (chat_id, reminder_id))
            return cur.rowcount > 0

    def backup_to(self, destination: Path) -> None:
        source_path = self.db_path.resolve()
        destination = destination.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"SQLite source does not exist: {source_path}")
        if source_path == destination:
            raise ValueError("Source and destination must be different files.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with closing(sqlite3.connect(source_path, timeout=30)) as source:
                with closing(sqlite3.connect(temporary)) as target:
                    source.backup(target)
            with closing(sqlite3.connect(temporary, timeout=5)) as conn:
                result = conn.execute("PRAGMA quick_check").fetchone()
            if result != ("ok",):
                raise sqlite3.DatabaseError(f"SQLite backup integrity check failed: {result}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _row_to_reminder(row: sqlite3.Row) -> Reminder:
        done_at = parse_iso_utc(row["done_at"]) if row["done_at"] else None
        return Reminder(
            id=row["id"],
            chat_id=row["chat_id"],
            text=row["text"],
            remind_at=parse_iso_utc(row["remind_at"]),
            repeat_rule=row["repeat_rule"],
            is_archived=bool(row["is_archived"]),
            done_at=done_at,
            created_at=parse_iso_utc(row["created_at"]),
        )

    @staticmethod
    def _normalized_query(query: str) -> str:
        tokens = re.findall(r"[\wа-яё]+", query.lower(), flags=re.IGNORECASE)
        if not tokens:
            return '""'
        return " ".join(f"{token}*" for token in tokens)

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[\wа-яё]+", query.lower(), flags=re.IGNORECASE)
        if not tokens:
            return '""'
        return " ".join(f'{token}*' for token in tokens)
