"""Read-only legacy SQLite snapshot import for isolated migration rehearsals."""
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from .models import History, Reminder, Source, SourceVersion, Task, uid
from .service import CRMService, snapshot

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 10_000
COLUMNS = {
    "notes": ("id", "chat_id", "text", "created_at", "is_archived"),
    "reminders": ("id", "chat_id", "text", "remind_at", "repeat_rule", "is_archived", "done_at", "created_at"),
}


class ImportError(Exception):
    """Public code only; no SQLite error, row text or local filename."""


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # This is the legacy bot's documented UTC storage contract, not server local time.
        return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        raise ImportError("legacy_date_invalid") from None


def _timezone(value):
    try:
        if not value:
            raise ValueError()
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError, TypeError):
        raise ImportError("legacy_timezone_required") from None


def _digest(path):
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ImportError("legacy_copy_too_large")
        return hashlib.sha256(data).hexdigest()
    except OSError:
        raise ImportError("legacy_copy_unavailable") from None


def _load(path, chat, timezone, now, expected=None):
    _timezone(timezone)
    if type(chat) is not int:
        raise ImportError("legacy_chat_required")
    path = Path(path).resolve()
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ImportError("legacy_copy_not_standalone")
    digest = _digest(path)
    if expected is not None and expected != digest:
        raise ImportError("legacy_snapshot_changed")
    rows, settings = [], None
    try:
        # Require a standalone backup, never open the running bot's WAL database.
        with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.set_progress_handler(lambda: 1, 20_000_000)
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ImportError("legacy_copy_invalid")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, columns in COLUMNS.items():
                if table not in tables or not set(columns) <= {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
                    raise ImportError("legacy_schema_unsupported")
                for row in conn.execute(f"SELECT {','.join(columns)} FROM {table} WHERE chat_id=? ORDER BY id LIMIT ?", (chat, MAX_ROWS + 1)):
                    value = dict(row)
                    if len(rows) >= MAX_ROWS:
                        raise ImportError("legacy_row_limit")
                    if type(value["id"]) is not int or value["id"] <= 0 or value["is_archived"] not in (0, 1):
                        raise ImportError("legacy_record_invalid")
                    if not isinstance(value["text"], str) or not value["text"].strip() or len(value["text"]) > 30_000:
                        raise ImportError("legacy_text_invalid")
                    _date(value["created_at"])
                    if table == "reminders":
                        _date(value["remind_at"])
                        if value["done_at"]:
                            _date(value["done_at"])
                        if value["repeat_rule"] is not None and (not isinstance(value["repeat_rule"], str) or len(value["repeat_rule"]) > 2000):
                            raise ImportError("legacy_record_invalid")
                    rows.append((table, value))
            if "chat_settings" in tables:
                settings_row = conn.execute("SELECT tz_offset_minutes,dayplan_enabled,dayplan_time FROM chat_settings WHERE chat_id=?", (chat,)).fetchone()
                settings = dict(settings_row) if settings_row else None
    except sqlite3.Error:
        raise ImportError("legacy_copy_invalid") from None
    if _digest(path) != digest:
        raise ImportError("legacy_snapshot_changed")
    counts = {table: sum(t == table for t, _ in rows) for table in COLUMNS}
    review = dict(repeats=sum(bool(v.get("repeat_rule")) for _, v in rows),
                  past_active_reminders=sum(t == "reminders" and not v["is_archived"] and not v.get("done_at")
                                            and _date(v["remind_at"]) <= now for t, v in rows),
                  all_reminders_disabled=counts["reminders"])
    return dict(snapshot_sha256=digest, counts=counts, review=review), rows, settings


def inspect_legacy(path, chat, timezone, *, now=None):
    return _load(path, chat, timezone, now or datetime.now(UTC))[0]


def import_legacy(factory, path, owner, chat, timezone, namespace, expected_sha256, *, now=None):
    database = factory.kw["bind"].url.database or ""
    if not (database.startswith("personal_crm_test") or re.fullmatch(r"personal_crm_restore_[a-z0-9_]+", database)):
        raise ImportError("legacy_rehearsal_database_required")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", namespace):
        raise ImportError("legacy_namespace_invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256 or ""):
        raise ImportError("legacy_preview_required")
    now = now or datetime.now(UTC)
    report, rows, settings = _load(path, chat, timezone, now, expected_sha256)
    created = skipped = 0
    with factory.begin() as s:
        profile = CRMService.owner(s, owner)
        if profile.timezone != timezone:
            raise ImportError("legacy_timezone_conflict")
        for table, value in rows:
            record_hash = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            account, external = "legacy:" + namespace, f"{table}:{value['id']}"
            source = s.scalar(select(Source).where(Source.owner_id == owner, Source.channel == "owner",
                                                    Source.account == account, Source.external_id == external))
            if source:
                old = s.scalar(select(SourceVersion).where(SourceVersion.source_id == source.id, SourceVersion.revision == 1))
                if not old or (old.channel_metadata or {}).get("legacy", {}).get("row_sha256") != record_hash:
                    raise ImportError("legacy_record_conflict")
                skipped += 1
                continue
            source = Source(owner_id=owner, channel="owner", account=account, external_id=external)
            s.add(source); s.flush()
            metadata = {k: v for k, v in value.items() if k not in ("text", "chat_id")}
            metadata.update(table=table, namespace=namespace, row_sha256=record_hash,
                            snapshot_sha256=report["snapshot_sha256"], timezone=timezone,
                            old_settings=settings, repeat_rule=value.get("repeat_rule"), reminder_disabled=True)
            version = SourceVersion(source_id=source.id, revision=1, text=value["text"], status="processed",
                                    original_at=_date(value["created_at"]), received_at=now, channel_metadata={"legacy": metadata})
            s.add(version); s.flush()
            state = "done" if value.get("done_at") else ("cancelled" if value["is_archived"] else "active")
            task = Task(owner_id=owner, source_version_id=version.id, title=value["text"],
                        kind="note" if table == "notes" else "task", state=state, created_at=_date(value["created_at"]))
            s.add(task); s.flush()
            if table == "reminders":
                s.add(Reminder(owner_id=owner, task_id=task.id, task_version=task.version,
                               at=_date(value["remind_at"]), active=False))
            version.result = dict(status="imported", task_id=task.id, review_required=table == "reminders")
            s.add(History(owner_id=owner, task_id=task.id, task_version=task.version, actor="owner",
                          reason="legacy_import", reference=version.id, before=None, after=snapshot(task), created_at=now))
            created += 1
    return {**report, "created": created, "skipped": skipped, "status": "imported_for_review"}
