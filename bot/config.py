from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: Path
    log_level: str = "INFO"
    log_path: Path = Path("bot.log")
    interaction_log_path: Path = Path("logs/interactions.log")
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5
    default_tz_offset_minutes: int = 0
    allowed_user_ids: frozenset[int] = frozenset()
    trainer_db_path: Path | None = None
    exercises_path: Path = Path("exercises.json")
    trainer_timezone: str = "Europe/Moscow"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(override=False)
        token = os.getenv("BOT_TOKEN", "").strip()
        db_path = Path(os.getenv("BOT_DB_PATH", "notes.db")).expanduser().resolve()
        log_level = os.getenv("BOT_LOG_LEVEL", "INFO").strip().upper() or "INFO"
        log_path = Path(os.getenv("BOT_LOG_PATH", "bot.log")).expanduser().resolve()
        interaction_log_path = Path(os.getenv("BOT_INTERACTION_LOG_PATH", "logs/interactions.log")).expanduser().resolve()
        log_max_bytes = _parse_int_env("BOT_LOG_MAX_BYTES", 5 * 1024 * 1024, minimum=1)
        log_backup_count = _parse_int_env("BOT_LOG_BACKUP_COUNT", 5, minimum=0)
        default_tz = _parse_int_env("BOT_DEFAULT_TZ_MINUTES", 0, minimum=-14 * 60, maximum=14 * 60)
        allowed_user_ids = _parse_user_ids(os.getenv("BOT_ALLOWED_USER_IDS", ""))
        trainer_db_raw = os.getenv("BOT_TRAINER_DB_PATH", "").strip()
        trainer_db_path = Path(trainer_db_raw).expanduser().resolve() if trainer_db_raw else db_path.with_name("workouts.sqlite3")
        exercises_path = Path(os.getenv("BOT_EXERCISES_PATH", "exercises.json")).expanduser().resolve()
        trainer_timezone = os.getenv("BOT_TRAINER_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
        if log_path == interaction_log_path:
            raise ValueError("BOT_LOG_PATH и BOT_INTERACTION_LOG_PATH должны указывать на разные файлы.")
        return cls(
            bot_token=token,
            db_path=db_path,
            log_level=log_level,
            log_path=log_path,
            interaction_log_path=interaction_log_path,
            log_max_bytes=log_max_bytes,
            log_backup_count=log_backup_count,
            default_tz_offset_minutes=default_tz,
            allowed_user_ids=allowed_user_ids,
            trainer_db_path=trainer_db_path,
            exercises_path=exercises_path,
            trainer_timezone=trainer_timezone,
        )


def _parse_user_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            user_id = int(value)
        except ValueError as exc:
            raise ValueError("BOT_ALLOWED_USER_IDS должен содержать целые Telegram user ID через запятую.") from exc
        if user_id <= 0:
            raise ValueError("BOT_ALLOWED_USER_IDS должен содержать положительные Telegram user ID.")
        ids.add(user_id)
    return frozenset(ids)


def _parse_int_env(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом.") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} должен быть не меньше {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} должен быть не больше {maximum}.")
    return value
