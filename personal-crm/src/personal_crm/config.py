import os
from dataclasses import dataclass, field
from .integration_config import AIConfig, TelegramConfig


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    owner_id: str = ""
    owner_token: str = field(default="", repr=False)
    mail_token: str = field(default="", repr=False)
    timezone: str | None = None
    ai: AIConfig = field(default_factory=AIConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("CRM_DATABASE_URL", ""),
            os.getenv("CRM_OWNER_ID", ""),
            os.getenv("CRM_OWNER_TOKEN", ""),
            os.getenv("CRM_FAKE_MAIL_TOKEN", ""),
            os.getenv("CRM_TIMEZONE") or None,
            AIConfig.from_env(), TelegramConfig.from_env(),
        )
