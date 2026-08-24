from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from bot.application import create_application
from bot.config import Settings


TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")


class SecretRedactionFilter(logging.Filter):
    def __init__(self, *secrets: str) -> None:
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "<redacted>")
        record.msg = TELEGRAM_TOKEN_RE.sub("<redacted>", message)
        record.args = ()
        return True


def _rotating_handler(path: Path, settings: Settings, redaction_filter: logging.Filter) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.addFilter(redaction_filter)
    return handler


def main() -> None:
    settings = Settings.from_env()
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.interaction_log_path.parent.mkdir(parents=True, exist_ok=True)
    redaction_filter = SecretRedactionFilter(settings.bot_token)
    interaction_handler = _rotating_handler(settings.interaction_log_path, settings, redaction_filter)
    interaction_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    interaction_logger = logging.getLogger("bot.interactions")
    interaction_logger.setLevel(logging.INFO)
    interaction_logger.handlers.clear()
    interaction_logger.addHandler(interaction_handler)
    interaction_logger.propagate = False
    file_handler = _rotating_handler(settings.log_path, settings, redaction_filter)
    stream_handler = logging.StreamHandler()
    stream_handler.addFilter(redaction_filter)
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=getattr(logging, settings.log_level, logging.INFO),
        handlers=[
            file_handler,
            stream_handler,
        ],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    app = create_application(settings)
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
