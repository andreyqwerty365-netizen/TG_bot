import os
from dataclasses import dataclass, field
from .integration_config import AIConfig, TelegramConfig
from .mail import MailConfig
from .planning_config import PlanningPolicy
from .auth_config import WebAuthConfig


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    owner_id: str = ""
    owner_token: str = field(default="", repr=False)
    mail_token: str = field(default="", repr=False)
    timezone: str | None = None
    ai: AIConfig = field(default_factory=AIConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    mail: MailConfig = field(default_factory=MailConfig)
    planning: PlanningPolicy = field(default_factory=PlanningPolicy)
    web_auth: WebAuthConfig = field(default_factory=WebAuthConfig)
    environment: str = 'development'

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("CRM_DATABASE_URL", ""),
            os.getenv("CRM_OWNER_ID", ""),
            os.getenv("CRM_OWNER_TOKEN", ""),
            os.getenv("CRM_FAKE_MAIL_TOKEN", ""),
            os.getenv("CRM_TIMEZONE") or None,
            AIConfig.from_env(), TelegramConfig.from_env(), MailConfig.from_env(), PlanningPolicy.from_env(),
            WebAuthConfig.from_env(), os.getenv('CRM_ENVIRONMENT','development'),
        )
