import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    owner_id: str = ""
    owner_token: str = field(default="", repr=False)
    mail_token: str = field(default="", repr=False)
    timezone: str | None = None

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("CRM_DATABASE_URL", ""),
            os.getenv("CRM_OWNER_ID", ""),
            os.getenv("CRM_OWNER_TOKEN", ""),
            os.getenv("CRM_FAKE_MAIL_TOKEN", ""),
            os.getenv("CRM_TIMEZONE") or None,
        )
